import { LazyViewBoundary } from "../../../../components/ui/LazyViewBoundary";
import { type MapProjection } from "../../types/report";
import { type BundleMapPlace } from "../../model/mapPlaces";
import React, { lazy, Suspense } from 'react';
interface BundleMapLeafletLazyProps {
    places: BundleMapPlace[];
    routes: MapProjection['content']['routes'];
    selectedEntityId: string | null;
    onSelectEntity: (entityId: string) => void;
    linkedEntityId?: string | null;
    onLinkEntity?: (entityId: string | null) => void;
    overlayOffset?: number;
}
const BundleMapLeafletImpl = lazy(() => import('./BundleMapLeaflet').then((module) => ({
    default: module.BundleMapLeaflet,
})));
export const BundleMapLeafletLazy: React.FC<BundleMapLeafletLazyProps> = (props) => (<LazyViewBoundary message="地图没能加载出来。" retryLabel="重新加载页面">
    <Suspense fallback={(<div data-testid="bundle-map-loading" className="flex h-full items-center justify-center bg-surface text-xs text-ink-muted">
        地图加载中…
      </div>)}>
      <BundleMapLeafletImpl {...props}/>
    </Suspense>
  </LazyViewBoundary>);
