import type { PlaceIdentity } from '../types/planner';

function city(
  id: string,
  name: string,
  latitude: number,
  longitude: number,
  adminPath: string[],
): PlaceIdentity {
  return {
    place_id: `inspiration_${id}`,
    provider: 'manual_verified',
    kind: 'city',
    name,
    display_name: name,
    country_code: 'CN',
    latitude,
    longitude,
    admin_path: adminPath,
  };
}

export const INSPIRATION_PLACES = {
  beijing: city('beijing', '北京', 39.9042, 116.4074, ['北京']),
  chengdu: city('chengdu', '成都', 30.5728, 104.0668, ['四川', '成都']),
  chongqing: city('chongqing', '重庆', 29.563, 106.5516, ['重庆']),
  shanghai: city('shanghai', '上海', 31.2304, 121.4737, ['上海']),
  suzhou: city('suzhou', '苏州', 31.2989, 120.5853, ['江苏', '苏州']),
  hangzhou: city('hangzhou', '杭州', 30.2741, 120.1551, ['浙江', '杭州']),
  xian: city('xian', '西安', 34.3416, 108.9398, ['陕西', '西安']),
  dunhuang: city('dunhuang', '敦煌', 40.1421, 94.6619, ['甘肃', '酒泉', '敦煌']),
  zhangye: city('zhangye', '张掖', 38.9259, 100.4498, ['甘肃', '张掖']),
  guangzhou: city('guangzhou', '广州', 23.1291, 113.2644, ['广东', '广州']),
  haikou: city('haikou', '海口', 20.044, 110.1999, ['海南', '海口']),
  sanya: city('sanya', '三亚', 18.2528, 109.5119, ['海南', '三亚']),
} as const;
