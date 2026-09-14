"""Temporal, drug-group-disjoint fitting with separate probability calibration."""
import warnings
from collections import Counter
from datetime import UTC, datetime

from .data import TARGET, build_dataset, digest, timestamp
from .features import FEATURE_VERSION, expanded_features, phase


def temporal_split(rows, train_until: str, calibrate_until: str):
    train_end, cal_end = timestamp(train_until), timestamp(calibrate_until)
    if train_end >= cal_end:
        raise ValueError("train_until must precede calibrate_until.")
    splits = {"train": [], "calibration": [], "test": []}
    excluded = Counter()
    for row in rows:
        label = row["label"]
        prediction, known = timestamp(label["prediction_at"]), timestamp(label["known_at"])
        if prediction <= train_end and known <= train_end:
            splits["train"].append(row)
        elif train_end < prediction <= cal_end and known <= cal_end:
            splits["calibration"].append(row)
        elif prediction > cal_end:
            splits["test"].append(row)
        else:
            excluded["outcome_unavailable_at_fit_boundary"] += 1
    # Purge a drug family (across indications, aliases, sponsors and combinations)
    # from later partitions if its curator-assigned group is already in an earlier one.
    prior_groups = set()
    for key in splits:
        retained = []
        for row in splits[key]:
            if row["label"]["drug_group"] in prior_groups:
                excluded["drug_group_overlap"] += 1
            else:
                retained.append(row)
        splits[key] = retained
        prior_groups.update(r["label"]["drug_group"] for r in retained)
    return splits, dict(excluded)


def metrics(y, probabilities):
    import numpy as np
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

    p, y = np.asarray(probabilities), np.asarray(y)
    bins = []
    for lower in (0.0, 0.2, 0.4, 0.6, 0.8):
        selected = (p >= lower) & (p < lower + 0.2 if lower < 0.8 else p <= 1)
        if selected.any():
            bins.append({"lower": lower, "count": int(selected.sum()),
                         "mean_prediction": float(p[selected].mean()),
                         "observed_success_rate": float(y[selected].mean())})
    return {"n": len(y), "positive": int(y.sum()), "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, p, labels=[0, 1])),
            "roc_auc": float(roc_auc_score(y, p)) if len(set(y)) == 2 else None,
            "average_precision": float(average_precision_score(y, p)) if len(set(y)) == 2 else None,
            "calibration_bins": bins}


def train(snapshots, labels, *, train_until: str, calibrate_until: str, as_of: str):
    import numpy as np
    import sklearn
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    if not timestamp(train_until) < timestamp(calibrate_until) < timestamp(as_of):
        raise ValueError("Require train_until < calibrate_until < as_of.")
    if timestamp(as_of) > datetime.now(UTC):
        raise ValueError("as_of cannot be in the future.")
    rows, exclusions = build_dataset(snapshots, labels, as_of)
    splits, split_exclusions = temporal_split(rows, train_until, calibrate_until)
    for key, minimum in (("train", 100), ("calibration", 40), ("test", 40)):
        counts = Counter(r["label"]["outcome"] for r in splits[key])
        if len(splits[key]) < minimum or min(counts.get(0, 0), counts.get(1, 0)) < 10:
            raise ValueError(f"Insufficient {key} data after exclusions: {len(splits[key])} trials, "
                             f"classes {dict(counts)}. Need {minimum} trials and 10 per class. "
                             f"Exclusions: {exclusions | split_exclusions}")
    vec = DictVectorizer(sparse=False)
    scaler = StandardScaler(with_mean=False)
    x = scaler.fit_transform(vec.fit_transform([
        expanded_features(r["snapshot"]["study"]) for r in splits["train"]]))
    y_train = [r["label"]["outcome"] for r in splits["train"]]
    model = LogisticRegression(C=1.0, max_iter=2000, random_state=17)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        model.fit(x, y_train)
        x_cal = scaler.transform(vec.transform([
            expanded_features(r["snapshot"]["study"]) for r in splits["calibration"]]))
        calibration = LogisticRegression(C=1.0, max_iter=2000, random_state=17)
        calibration.fit(model.decision_function(x_cal).reshape(-1, 1),
                        [r["label"]["outcome"] for r in splits["calibration"]])
    x_test = scaler.transform(vec.transform([
        expanded_features(r["snapshot"]["study"]) for r in splits["test"]]))
    p_test = calibration.predict_proba(model.decision_function(x_test).reshape(-1, 1))[:, 1]
    y_test = [r["label"]["outcome"] for r in splits["test"]]
    prior = sum(y_train) / len(y_train)
    phases = sorted({phase(r["snapshot"]["study"]) for r in splits["train"]})
    phase_rates = {}
    for key in phases:
        outcomes = [r["label"]["outcome"] for r in splits["train"]
                    if phase(r["snapshot"]["study"]) == key]
        # Laplace smoothing prevents extreme priors from tiny strata.
        phase_rates[key] = (sum(outcomes) + 1) / (len(outcomes) + 2)
    report = {"model": metrics(y_test, p_test),
              "training_prevalence_baseline": metrics(y_test, [prior] * len(y_test)),
              "phase_baseline": metrics(y_test, [phase_rates.get(phase(r["snapshot"]["study"]), prior)
                                                   for r in splits["test"]]),
              "by_phase": {}}
    for key in sorted({phase(r["snapshot"]["study"]) for r in splits["test"]}):
        ix = [i for i, r in enumerate(splits["test"]) if phase(r["snapshot"]["study"]) == key]
        report["by_phase"][key] = metrics([y_test[i] for i in ix], p_test[ix])
    model_metrics = report["model"]
    passes = all(model_metrics[m] < report[b][m] for m in ("brier", "log_loss")
                 for b in ("training_prevalence_baseline", "phase_baseline"))
    passes = bool(passes and model_metrics["roc_auc"] >= 0.55 and calibration.coef_[0, 0] > 0)
    artifact = {
        "artifact_version": 1, "feature_version": FEATURE_VERSION, "target": TARGET,
        "algorithm": "standardized_logistic_regression_with_sigmoid_calibration",
        "status": "research_candidate" if passes else "evaluation_failed",
        "trained_at": datetime.now(UTC).isoformat(), "sklearn_version": sklearn.__version__,
        "train_until": train_until, "calibrate_until": calibrate_until, "as_of": as_of,
        "feature_names": vec.get_feature_names_out().tolist(), "scale": scaler.scale_.tolist(),
        "coefficients": model.coef_[0].tolist(), "intercept": float(model.intercept_[0]),
        "calibration_slope": float(calibration.coef_[0, 0]),
        "calibration_intercept": float(calibration.intercept_[0]),
        "supported_phases": phases, "training_prevalence": prior,
        "splits": {key: {"n": len(group),
                         "nct_ids": [r["label"]["nct_id"] for r in group],
                         "drug_groups": sorted({r["label"]["drug_group"] for r in group})}
                   for key, group in splits.items()},
        "dataset_hash": digest(rows), "exclusions": {**exclusions, **split_exclusions},
        "evaluation": report,
        "limitations": [
            "Research baseline; endpoint success is not regulatory approval or commercial success.",
            "No prospective validation. Minimum sample gates do not establish clinical validity.",
            "Design-only features omit mechanism, prior efficacy, safety and disease biology.",
            "Drug-family grouping and outcome labels require independent human adjudication.",
            "Retrospective label curation may introduce selection and reporting bias.",
            "Do not repeatedly tune on this test cohort; reserve a new untouched cohort for model changes.",
        ],
    }
    # JSON coefficients are sufficient for serving; no executable pickle is loaded.
    if not np.isfinite(model.coef_).all():
        raise ValueError("Non-finite model coefficients.")
    artifact["model_id"] = digest(artifact)
    return artifact
