import React from 'react';
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

const SouthwestArtwork: React.FC = () => (
  <>
    <svg className="atlas-artwork atlas-terrain atlas-parallax-far" viewBox="0 0 640 780" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <path d="M-40 142C55 92 87 164 170 129S302 50 388 94s132 14 209-35 116 4 83 76-109 71-114 142 73 95 24 157-151 18-198 96 5 137-80 145-132-73-218-44-110 88-134 27" />
      <path d="M-35 208c85-52 144 18 224-12s116-94 204-56 118 26 192-19 107-7 72 57-105 61-111 123 48 95-20 139-133 5-184 72-3 122-81 128-112-62-191-40-105 71-123 12" />
      <path d="M-20 285c84-41 136 11 207-12s110-68 184-40 114 31 177 4 101 3 65 50-92 46-102 98 34 82-26 119-116 3-164 57-12 102-77 107-95-47-164-31-91 58-109 10" />
      <path className="atlas-river" d="M512-20c-83 105-23 159-86 236s-23 143-86 207-37 127-105 196-69 122-45 189" />
      <path className="atlas-mountain" d="M-20 625 72 516l43 47 81-122 71 105 54-63 96 142Z" />
      <path className="atlas-mountain atlas-mountain-far" d="m294 670 88-113 42 37 80-107 122 183Z" />
    </svg>
    <svg className="atlas-artwork atlas-route atlas-parallax-near" viewBox="0 0 640 780" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <path className="atlas-route-shadow" d="M505 138C445 205 419 238 381 301S285 406 262 478 183 564 135 622" />
      <path className="atlas-route-line" pathLength="1" d="M505 138C445 205 419 238 381 301S285 406 262 478 183 564 135 622" />
      <g className="atlas-map-pin atlas-pin-one" transform="translate(505 138)"><circle r="17" /><text y="5">1</text></g>
      <g className="atlas-map-pin atlas-pin-two" transform="translate(262 478)"><circle r="17" /><text y="5">2</text></g>
      <g className="atlas-map-pin atlas-pin-three" transform="translate(135 622)"><circle r="17" /><text y="5">3</text></g>
      <g transform="translate(370 320) rotate(-24)"><g className="atlas-plane"><path d="m0 7 28-11-12 24-5-9-9 3 5-9-7-2Z" /></g></g>
    </svg>
  </>
);

const JiangnanArtwork: React.FC = () => (
  <svg className="atlas-artwork atlas-jiangnan-art atlas-parallax-far" viewBox="0 0 640 780" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <circle className="atlas-jiangnan-moon" cx="492" cy="174" r="102" />
    <g className="atlas-jiangnan-orbits">
      <circle cx="492" cy="174" r="132" />
      <circle cx="492" cy="174" r="164" />
    </g>
    <g className="atlas-willow">
      <path d="M42-20c20 116 6 212-32 318M82-20c4 128-4 216-30 314M124-20c-4 100-4 188-32 278" />
      <path d="M16 160c38 10 68 4 98-20M4 220c40 10 73 2 104-24M64 112c34 4 58-4 82-24" />
    </g>
    <g className="atlas-jiangnan-houses">
      <path d="M28 500V406l66-48 66 48v94M48 406h92M70 500v-58h42v58M166 500v-76l54-39 55 39v76M184 424h72" />
      <path d="M16 500h290" />
    </g>
    <g className="atlas-jiangnan-bridge">
      <path d="M96 600c54-146 188-146 242 0" />
      <path d="M76 600h282M108 600c50-102 176-102 218 0" />
      <path d="M126 522v78M300 522v78" />
    </g>
    <g className="atlas-water-lines">
      <path d="M-40 550c88-24 144 22 232 0s148-22 236 0 148 22 252-2" />
      <path d="M-50 626c96-22 164 20 252 0s148-20 236 0 144 20 242 0" />
      <path d="M-20 684c82-18 140 18 222 0s144-18 226 0 144 18 232 0" />
      <path d="M18 728c70-14 124 14 194 0s124-14 194 0 124 14 194 0" />
    </g>
    <g className="atlas-boat" transform="translate(414 538)">
      <path d="M0 42h106l-18 20H20Z" />
      <path d="M24 42c8-44 54-44 62 0M53 0v42" />
      <path d="M102 6v36M102 6l22 14" />
    </g>
  </svg>
);

const NorthwestArtwork: React.FC = () => (
  <svg className="atlas-artwork atlas-northwest-art atlas-parallax-far" viewBox="0 0 640 780" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <g className="atlas-desert-orbits">
      <ellipse cx="480" cy="192" rx="166" ry="138" />
      <ellipse cx="480" cy="192" rx="208" ry="178" />
      <path d="M240 192h480M480-40v464" />
    </g>
    <circle className="atlas-desert-sun" cx="480" cy="192" r="96" />
    <path className="atlas-dune atlas-dune-far" d="M-60 548c126-18 168-152 296-128 94 18 122 104 220 88 80-13 132-86 224-64v336H-60Z" />
    <path className="atlas-dune atlas-dune-mid" d="M-60 632c134-86 234-74 330-10 104 70 184 12 262-56 58-50 108-54 168-28v242H-60Z" />
    <path className="atlas-dune atlas-dune-near" d="M-40 728c108-102 222-116 338-34 106 74 214 50 342-22v108H-40Z" />
    <g className="atlas-desert-contours">
      <path d="M-20 576c126-52 202-48 292 4M-28 604c132-48 214-40 300 10M350 618c102-18 182-76 292-72M370 650c96-20 174-68 280-66" />
    </g>
    <path className="atlas-desert-road" d="M336 780c-4-88 22-132 74-176 42-36 54-70 38-112" />
    <g className="atlas-desert-stars">
      <path d="M122 156v22M111 167h22M214 88v16M206 96h16M574 328v18M565 337h18" />
    </g>
  </svg>
);

const IslandArtwork: React.FC = () => (
  <svg className="atlas-artwork atlas-island-art atlas-parallax-far" viewBox="0 0 640 780" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <circle className="atlas-island-sun" cx="482" cy="190" r="94" />
    <g className="atlas-island-orbits">
      <circle cx="482" cy="190" r="128" />
      <path d="M314 190h336M482 22v336" />
    </g>
    <g className="atlas-palm" transform="translate(556 304)">
      <path d="M0 160C-4 96 4 42 26-8" />
      <path d="M26-8c-42-34-78-28-102-8 40 2 72 8 102 8ZM26-8c-4-48 16-76 44-88-12 38-24 64-44 88ZM26-8c38-34 74-34 104-18-40 8-70 14-104 18ZM26-8c-36 2-62 20-76 48 30-16 54-28 76-48Z" />
    </g>
    <g className="atlas-sailboat" transform="translate(360 404)">
      <path d="M0 96h124l-24 24H26Z" />
      <path d="M60 0v96M54 12 8 84h46ZM70 22l44 62H70Z" />
    </g>
    <g className="atlas-waves atlas-waves-back">
      <path d="M-80 492c70-44 118 44 188 0s118 44 188 0 118 44 188 0 118 44 188 0" />
      <path d="M-60 552c64-38 110 38 174 0s110 38 174 0 110 38 174 0 110 38 174 0" />
    </g>
    <g className="atlas-waves atlas-waves-front">
      <path d="M-90 634c76-50 126 50 202 0s126 50 202 0 126 50 202 0 126 50 202 0" />
      <path d="M-70 706c70-42 118 42 188 0s118 42 188 0 118 42 188 0 118 42 188 0" />
    </g>
    <g className="atlas-sea-sparkles">
      <circle cx="146" cy="514" r="4" />
      <circle cx="266" cy="588" r="3" />
      <circle cx="510" cy="580" r="4" />
      <path d="M194 446v20M184 456h20M524 476v16M516 484h16" />
    </g>
  </svg>
);

export const AtlasSceneArtwork: React.FC<{ scene: AtlasSceneId }> = ({ scene }) => {
  if (scene === 'jiangnan') return <JiangnanArtwork />;
  if (scene === 'northwest') return <NorthwestArtwork />;
  if (scene === 'island') return <IslandArtwork />;
  return <SouthwestArtwork />;
};
