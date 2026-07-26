"""Deterministic gate between arbitrary models and the validated controller."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ControllerCompatibilityResult:
    standard_simulation_compatible: bool
    closed_loop_compatible: bool
    required_variables_found: list[str] = field(default_factory=list)
    required_meters_found: list[str] = field(default_factory=list)
    candidate_actuator_targets: list[str] = field(default_factory=list)
    confirmed_actuator_target: str | None = None
    missing_requirements: list[str] = field(default_factory=list)
    compatibility_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ControllerCompatibilityAnalyser:
    """Never promotes an actuator based on an LLM response or name similarity."""

    REQUIRED_VARIABLE_TERMS = (
        "Zone Mean Air Temperature",
        "Site Outdoor Air Drybulb Temperature",
    )
    REQUIRED_METER_TERMS = ("Electricity:Facility",)
    VALIDATED_ACTUATOR = "MAIN COOLING COIL 1 OUTLET NODE"

    def __init__(self, validated_model_path: Path | str | None = None) -> None:
        self.validated_model_hash: str | None = None
        if validated_model_path:
            path = Path(validated_model_path)
            if path.is_file():
                self.validated_model_hash = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()

    def analyse(
        self,
        *,
        idf_path: Path | str,
        validation_succeeded: bool,
        output_variables_text: str = "",
        output_meters_text: str = "",
        verified_actuator_inventory: list[str] | None = None,
    ) -> ControllerCompatibilityResult:
        variables = [
            term
            for term in self.REQUIRED_VARIABLE_TERMS
            if term.casefold() in output_variables_text.casefold()
        ]
        meters = [
            term
            for term in self.REQUIRED_METER_TERMS
            if term.casefold() in output_meters_text.casefold()
        ]
        inventory = verified_actuator_inventory or []
        candidate_targets = sorted(set(inventory))
        current_hash = hashlib.sha256(Path(idf_path).read_bytes()).hexdigest()
        exact_validated_model = (
            self.validated_model_hash is not None
            and current_hash == self.validated_model_hash
        )
        actuator_confirmed = (
            exact_validated_model and self.VALIDATED_ACTUATOR in inventory
        )

        missing: list[str] = []
        if len(variables) != len(self.REQUIRED_VARIABLE_TERMS):
            missing.append("required Runtime API temperature variables")
        if len(meters) != len(self.REQUIRED_METER_TERMS):
            missing.append("required facility electricity meter")
        if not actuator_confirmed:
            missing.append("deterministically verified System Node Setpoint actuator")

        closed_loop = validation_succeeded and not missing
        notes = [
            "Standard simulation does not inject Runtime API actuators.",
            "Node-name similarity is not actuator verification.",
        ]
        if exact_validated_model:
            notes.append("IDF hash matches the validated project model.")
        else:
            notes.append("IDF hash does not match the validated project model.")

        return ControllerCompatibilityResult(
            standard_simulation_compatible=validation_succeeded,
            closed_loop_compatible=closed_loop,
            required_variables_found=variables,
            required_meters_found=meters,
            candidate_actuator_targets=candidate_targets,
            confirmed_actuator_target=(
                self.VALIDATED_ACTUATOR if actuator_confirmed else None
            ),
            missing_requirements=missing,
            compatibility_notes=notes,
        )
