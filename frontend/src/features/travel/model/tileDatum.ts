export function withinChinaCoordinateBox(lng: number, lat: number): boolean {
    return lng > 73.66 && lng < 135.05 && lat > 3.86 && lat < 53.55;
}
const GCJ_A = 6378245.0;
const GCJ_EE = 0.00669342162296594323;
function transformLat(x: number, y: number): number {
    let ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * Math.sqrt(Math.abs(x));
    ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
    ret += ((20.0 * Math.sin(y * Math.PI) + 40.0 * Math.sin((y / 3.0) * Math.PI)) * 2.0) / 3.0;
    ret += ((160.0 * Math.sin((y / 12.0) * Math.PI) + 320 * Math.sin((y * Math.PI) / 30.0)) * 2.0) / 3.0;
    return ret;
}
function transformLng(x: number, y: number): number {
    let ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * Math.sqrt(Math.abs(x));
    ret += ((20.0 * Math.sin(6.0 * x * Math.PI) + 20.0 * Math.sin(2.0 * x * Math.PI)) * 2.0) / 3.0;
    ret += ((20.0 * Math.sin(x * Math.PI) + 40.0 * Math.sin((x / 3.0) * Math.PI)) * 2.0) / 3.0;
    ret += ((150.0 * Math.sin((x / 12.0) * Math.PI) + 300.0 * Math.sin((x / 30.0) * Math.PI)) * 2.0) / 3.0;
    return ret;
}
function gcjOffset(lng: number, lat: number): [
    number,
    number
] {
    let dlat = transformLat(lng - 105.0, lat - 35.0);
    let dlng = transformLng(lng - 105.0, lat - 35.0);
    const radlat = (lat / 180.0) * Math.PI;
    let magic = Math.sin(radlat);
    magic = 1 - GCJ_EE * magic * magic;
    const sqrtmagic = Math.sqrt(magic);
    dlat = (dlat * 180.0) / (((GCJ_A * (1 - GCJ_EE)) / (magic * sqrtmagic)) * Math.PI);
    dlng = (dlng * 180.0) / ((GCJ_A / sqrtmagic) * Math.cos(radlat) * Math.PI);
    return [dlng, dlat];
}
export function wgs84ToGcj02(lng: number, lat: number): [
    number,
    number
] {
    if (!withinChinaCoordinateBox(lng, lat))
        return [lng, lat];
    const [dlng, dlat] = gcjOffset(lng, lat);
    return [lng + dlng, lat + dlat];
}
// 存储坐标保持 WGS-84，仅在高德瓦片渲染前转换。
export function toTileDatum(latitude: number, longitude: number): [
    number,
    number
] {
    const [lng, lat] = wgs84ToGcj02(longitude, latitude);
    return [lat, lng];
}
interface MaybeLocated {
    latitude?: number | null;
    longitude?: number | null;
}
export function pointOnTileDatum(located: MaybeLocated | null | undefined): [
    number,
    number
] | null {
    if (!located || located.latitude == null || located.longitude == null)
        return null;
    return toTileDatum(located.latitude, located.longitude);
}
