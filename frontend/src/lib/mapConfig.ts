export interface MapTileConfig {
  url: string;
  attribution: string;
  subdomains?: string[];
}

const DEFAULT_TILE_URL = 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}';
const DEFAULT_TILE_ATTRIBUTION = '&copy; <a href="https://amap.com/">高德地图</a>';
const DEFAULT_TILE_SUBDOMAINS = ['1', '2', '3', '4'];

/** 默认值保持现网瓦片源；部署方可用 env 换成自建或其他瓦片服务。 */
export function resolveMapTileConfig(
  url: string | undefined,
  attribution: string | undefined,
): MapTileConfig {
  const resolvedUrl = url?.trim() || DEFAULT_TILE_URL;
  return {
    url: resolvedUrl,
    attribution: attribution?.trim() || DEFAULT_TILE_ATTRIBUTION,
    subdomains: resolvedUrl.includes('{s}') ? DEFAULT_TILE_SUBDOMAINS : undefined,
  };
}

export function getMapTileConfig(): MapTileConfig {
  return resolveMapTileConfig(
    import.meta.env.VITE_MAP_TILE_URL,
    import.meta.env.VITE_MAP_TILE_ATTRIBUTION,
  );
}
