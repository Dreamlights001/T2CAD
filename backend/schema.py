from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.cadgen_engine import number


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=50)
    label: str
    value: float = Field(allow_inf_nan=False, ge=-10000, le=10000)
    unit: Literal["mm", "deg", "count"] = "mm"


class Feature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$", max_length=50)
    name: str
    op: Literal["box", "cylinder", "gear", "extrude", "revolve", "cut_extrude", "hole",
                "union", "cut", "intersect", "fillet", "chamfer", "linear_pattern", "polar_pattern"]
    args: dict = Field(default_factory=dict)


class Design(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=100)
    parameters: list[Parameter] = Field(max_length=60)
    features: list[Feature] = Field(min_length=1, max_length=40)
    expected_size: list[float | str | None] | None = Field(default=None, min_length=3, max_length=3)

    @field_validator("expected_size", mode="before")
    @classmethod
    def normalize_unknown_dimensions(cls, value):
        if isinstance(value, list):
            return [None if isinstance(axis, str) and axis.strip().lower() == "null" else axis for axis in value]
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        for values in ([p.name for p in self.parameters], [f.id for f in self.features]):
            if len(values) != len(set(values)):
                raise ValueError("参数名或特征 ID 重复")
        parameters = {p.name: p.value for p in self.parameters}
        dimensions = []
        for axis, expected in zip("XYZ", self.expected_size or []):
            measured = None
            if expected is not None:
                try:
                    measured = number(expected, parameters)
                    if measured <= 0:
                        raise ValueError("目标尺寸必须大于零")
                except (ValueError, SyntaxError, ZeroDivisionError) as exc:
                    raise ValueError(f"expected_size 的 {axis} 轴无效: {exc}") from exc
            dimensions.append(measured)
        if len(self.features) == 1 and self.features[0].op == "gear":
            args = self.features[0].args
            if args.get("plane", "XY") == "XY" and "rotate" not in args:
                try:
                    module = number(args["module"], parameters)
                    teeth = number(args["teeth"], parameters)
                    beta = number(args.get("helix_angle", 0), parameters)
                except (KeyError, ValueError, SyntaxError, ZeroDivisionError):
                    pass  # The feature executor reports invalid gear arguments.
                else:
                    diameter = module * (teeth + 2)
                    mismatched_axes = [teeth % 2 != 0, teeth % 4 != 0]
                    if beta == 0 and any(value is not None and abs(value-diameter) < 1e-6 and mismatched_axes[axis]
                           for axis, value in enumerate(dimensions[:2])):
                        raise ValueError("齿顶圆直径不是齿轮的 XY 包围盒尺寸；当前齿数下两者不同。"
                                         "请保留模数、齿数和厚度，expected_size 使用 [null,null,厚度参数名]；"
                                         "null 必须是 JSON 空值。若用户明确要求矩形包围尺寸，请澄清约束。")
        return self


class MessageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    base_revision: str | None = None


class ParameterRequest(BaseModel):
    values: dict[str, float]
    base_revision: str
