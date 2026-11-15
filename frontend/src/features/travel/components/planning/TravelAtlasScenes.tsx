import { INSPIRATION_PLACES as PLACES } from '../../model/inspirationPlaces';
import type { PlaceIdentity } from '../../types/planner';

export type AtlasSceneId = 'southwest' | 'jiangnan' | 'northwest' | 'island';

export interface AtlasScene {
  id: AtlasSceneId;
  tab: string;
  subtitle: string;
  cardTitle: string;
  description: string;
  invitation: string;
  moment: readonly [string, string];
  highlights: readonly [string, string, string];
  origin: PlaceIdentity;
  destinations: readonly PlaceIdentity[];
  days: number;
  adults: number;
  budgetCny: number;
  primary: string;
  prompt: string;
}

export const ATLAS_SCENES: readonly AtlasScene[] = [
  {
    id: 'southwest',
    tab: '巴蜀',
    subtitle: '城市文化 · 地方美食 · 轻松节奏',
    cardTitle: '成都＋重庆 7 日',
    description: '两座城，把美食、人文和松弛节奏装进一周。',
    invitation: '喝碗茶，再沿街找小吃',
    moment: ['在茶馆坐一下午', '沿街尝几样小吃'],
    highlights: ['盖碗茶', '老街巷', '地方小吃'],
    origin: PLACES.beijing,
    destinations: [PLACES.chengdu, PLACES.chongqing],
    days: 7,
    adults: 2,
    budgetCny: 12000,
    primary: '轻松慢游',
    prompt: '想从北京去成都和重庆，7 天，2 位成人。想在老茶馆坐一下午，走街串巷尝几样小吃，喜欢地方文化，节奏轻松，总预算约 12000 元。',
  },
  {
    id: 'jiangnan',
    tab: '江南',
    subtitle: '园林水巷 · 沿河散步 · 江南风味',
    cardTitle: '苏州＋杭州 4 日',
    description: '园林、水巷与茶香，适合慢慢走的四天。',
    invitation: '逛完园林，在水巷边喝茶',
    moment: ['沿水巷慢慢走', '喝杯茶歇歇脚'],
    highlights: ['园林', '水巷', '茶香'],
    origin: PLACES.shanghai,
    destinations: [PLACES.suzhou, PLACES.hangzhou],
    days: 4,
    adults: 2,
    budgetCny: 6000,
    primary: '轻松慢游',
    prompt: '想从上海去苏州和杭州，4 天，2 位成人。想慢慢逛园林、沿水巷散步，留半天在茶馆喝茶歇脚，节奏轻松，总预算约 6000 元。',
  },
  {
    id: 'northwest',
    tab: '西北',
    subtitle: '石窟丹霞 · 戈壁公路 · 开阔节奏',
    cardTitle: '敦煌＋张掖 6 日',
    description: '石窟、丹霞与戈壁公路，一路向开阔处走。',
    invitation: '想看丹霞，也想等戈壁日落',
    moment: ['在石窟里看壁画', '等一场戈壁日落'],
    highlights: ['丹霞', '石窟', '戈壁日落'],
    origin: PLACES.xian,
    destinations: [PLACES.dunhuang, PLACES.zhangye],
    days: 6,
    adults: 2,
    budgetCny: 9000,
    primary: '人文体验',
    prompt: '想从西安去敦煌和张掖，6 天，2 位成人。想看丹霞和石窟壁画，也想在戈壁等一次日落，多留些停留时间，总预算约 9000 元。',
  },
  {
    id: 'island',
    tab: '海岛',
    subtitle: '海岸公路 · 热带风味 · 松弛假期',
    cardTitle: '海口＋三亚 5 日',
    description: '沿着海岸向南，把浪花、晚风和海鲜排进假期。',
    invitation: '早起逛市场，傍晚沿海走走',
    moment: ['逛早市吃早餐', '沿着海岸吹晚风'],
    highlights: ['早市早餐', '海岸散步', '海边晚风'],
    origin: PLACES.guangzhou,
    destinations: [PLACES.haikou, PLACES.sanya],
    days: 5,
    adults: 2,
    budgetCny: 8000,
    primary: '轻松慢游',
    prompt: '想从广州去海口和三亚，5 天，2 位成人。想逛早市吃当地早餐，沿海岸散步，傍晚留时间吹晚风，节奏轻松，住得舒服一点，总预算约 8000 元。',
  },
];
