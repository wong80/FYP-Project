"""MLflow packaging for an MLJAR AutoML model.

MLJAR saves a whole results directory rather than one object, so the model is
logged as an MLflow ``pyfunc`` whose artifact is that directory.
"""

from __future__ import annotations

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd

from .features import FEATURES

MLJAR_ARTIFACT = "mljar_results"


class MljarModel(mlflow.pyfunc.PythonModel):
    def load_context(self, context) -> None:
        from supervised import AutoML

        self._automl = AutoML(results_path=context.artifacts[MLJAR_ARTIFACT])

    def predict(self, context, model_input: pd.DataFrame, params=None) -> np.ndarray:
        # Power can't be negative; clamp here so gates, scorer and replay all see what is served.
        return np.asarray(self._automl.predict(model_input[FEATURES]), dtype=float).clip(min=0)


def log_mljar_model(results_path: str, registered_name: str) -> mlflow.models.model.ModelInfo:
    return mlflow.pyfunc.log_model(
        name="model",
        python_model=MljarModel(),
        artifacts={MLJAR_ARTIFACT: results_path},
        registered_model_name=registered_name,
        pip_requirements=["mljar-supervised==1.3.2"],
    )


def load(model_uri: str) -> mlflow.pyfunc.PyFuncModel:
    return mlflow.pyfunc.load_model(model_uri)
