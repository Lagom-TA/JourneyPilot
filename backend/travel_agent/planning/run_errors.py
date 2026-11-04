from dataclasses import dataclass


class RunNotFound(Exception):
    pass


@dataclass
class RunNotCancellable(Exception):
    current_status: str | None


class LockedIdentitySupplement(Exception):
    pass


@dataclass
class RunNotAcceptingSupplement(Exception):
    has_delivery: bool = False


class DeliveryBundleMissing(Exception):
    pass


@dataclass
class ReportRevisionChanged(Exception):
    current_bundle_id: str
