"""Select the ETA model to use in a simulator run."""

from dispatchsim.eta_model import ETAModel
from dispatchsim.eta_model.baseline import BaselineETAModel
from dispatchsim.eta_model.rush_hour import RushHourETAModel


def create_eta_model(name: str = "baseline") -> ETAModel:
    """Keep the original timing by default and reject unknown model names."""
    if name == "baseline":
        return BaselineETAModel()
    if name == "rush-hour":
        return RushHourETAModel()
    raise ValueError(f"unknown ETA model {name!r}; choose 'baseline' or 'rush-hour'")
