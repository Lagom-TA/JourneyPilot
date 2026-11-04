import type { PlaceIdentity } from '../../types/planner';

export type AtlasSceneId = 'southwest' | 'jiangnan' | 'northwest' | 'island';

export interface AtlasScene {
  id: AtlasSceneId;
  tab: string;
  subtitle: string;
  cardTitle: string;
  description: string;
  origin: PlaceIdentity;
  destinations: readonly PlaceIdentity[];
  days: number;
  adults: number;
  budgetCny: number;
  primary: string;
  prompt: string;
}

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

const PLACES = {
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

export const ATLAS_SCENES: readonly AtlasScene[] = [
  {
    id: 'southwest',
    tab: '巴蜀',
    subtitle: '城市文化 · 地方美食 · 轻松节奏',
    cardTitle: '成都＋重庆 7 日',
    description: '两座城，把美食、人文和松弛节奏装进一周。',
    origin: PLACES.beijing,
    destinations: [PLACES.chengdu, PLACES.chongqing],
    days: 7,
    adults: 2,
    budgetCny: 12000,
    primary: '轻松慢游',
    prompt: '国庆假期想从北京去成都和重庆，7 天，2 位成人，轻松一点，喜欢城市文化和地方美食，总预算约 12000 元。',
  },
  {
    id: 'jiangnan',
    tab: '江南',
    subtitle: '园林水巷 · 春日散步 · 江南风味',
    cardTitle: '苏州＋杭州 4 日',
    description: '园林、水巷与茶香，适合慢慢走的四天。',
    origin: PLACES.shanghai,
    destinations: [PLACES.suzhou, PLACES.hangzhou],
    days: 4,
    adults: 2,
    budgetCny: 6000,
    primary: '轻松慢游',
    prompt: '想从上海去苏州和杭州，4 天，2 位成人，逛园林、走水巷，节奏轻松，总预算约 6000 元。',
  },
  {
    id: 'northwest',
    tab: '西北',
    subtitle: '石窟丹霞 · 戈壁公路 · 开阔节奏',
    cardTitle: '敦煌＋张掖 6 日',
    description: '石窟、丹霞与戈壁公路，一路向开阔处走。',
    origin: PLACES.xian,
    destinations: [PLACES.dunhuang, PLACES.zhangye],
    days: 6,
    adults: 2,
    budgetCny: 9000,
    primary: '人文体验',
    prompt: '想从西安去敦煌和张掖，6 天，2 位成人，看丹霞、沙漠和石窟，总预算约 9000 元。',
  },
  {
    id: 'island',
    tab: '海岛',
    subtitle: '海岸公路 · 热带风味 · 松弛假期',
    cardTitle: '海口＋三亚 5 日',
    description: '沿着海岸向南，把浪花、晚风和海鲜排进假期。',
    origin: PLACES.guangzhou,
    destinations: [PLACES.haikou, PLACES.sanya],
    days: 5,
    adults: 2,
    budgetCny: 8000,
    primary: '轻松慢游',
    prompt: '想从广州去海口和三亚，5 天，2 位成人，想看海、吃海鲜，住得舒服一点，总预算约 8000 元。',
  },
];
