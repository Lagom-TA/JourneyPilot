from dataclasses import dataclass


class RunNotFound(Exception):
    pass


@dataclass
class RunNotCancellable(Exception):
    current_status: str | None


class LockedIdentitySupplement(Exception):
    pass


class RunNotAcceptingSupplement(Exception):
    pass


class DeliveryBundleMissing(Exception):
    pass


@dataclass
class ReportRevisionChanged(Exception):
    current_bundle_id: str
