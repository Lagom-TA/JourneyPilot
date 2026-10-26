"""只读的产品配置接口，数据来自数据库。"""

from fastapi import APIRouter, HTTPException

from travel_agent.storage.product_configuration_store import ProductConfigurationStore
from travel_agent.planning.requirements.product_contracts import TripPlannerConfiguration

router = APIRouter(prefix="/api/product", tags=["product"])
_store = ProductConfigurationStore()


@router.get("/trip-planner", response_model=TripPlannerConfiguration)
async def get_trip_planner_configuration() -> TripPlannerConfiguration:
    try:
        return await _store.get_trip_planner()
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
