from dataclasses import dataclass


@dataclass
class ChannelConfig:
    channel_id: str
    raw_visible: bool = True
    formula_visible: bool = False
    formula: str = ""

    def has_visible_series(self):
        return self.raw_visible or (self.formula_visible and bool(self.formula.strip()))
