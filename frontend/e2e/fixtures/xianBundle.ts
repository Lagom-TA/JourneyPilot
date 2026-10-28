const DELIVERY_BUNDLE_CONTRACT_VERSION = 'journeypilot.delivery_bundle.v10';
const TRIP_WORKSPACE_CONTRACT_VERSION = 'journeypilot.trip_workspace.v11';
const EVIDENCE = 'public_reference' as const;
const XI = 'amap:poi:xian';

type EntityType = 'visit_stop' | 'dining_stop' | 'lodging_stay' | 'transport_leg';
type TransportMode = 'flight' | 'high_speed_rail' | 'train' | 'coach' | 'ferry' | 'drive' | 'bus' | 'taxi' | 'ride_hailing' | 'metro' | 'walk' | 'bike' | 'tram' | 'other';
type TransportClass = 'long_distance' | 'public_transit' | 'flexible';
type ProjectionRole = 'full' | 'departure' | 'arrival' | 'check_in' | 'check_out';

function ref(entityType: EntityType, entityId: string) {
  return { entity_type: entityType, entity_id: entityId };
}

function endpoint(name: string, placeId: string, latitude: number, longitude: number) {
  return { name, place_id: placeId, station_code: null, latitude, longitude };
}

type FixtureEndpoint = ReturnType<typeof endpoint>;
type FixtureSegment = ReturnType<typeof segment>;

const points = {
  terracotta: endpoint('秦始皇帝陵博物院（兵马俑）', 'amap:poi:terracotta', 34.3848, 109.2785),
  lunchOne: endpoint('老白家水盆羊肉（临潼店）', 'amap:poi:lintong-lunch', 34.3725, 109.2137),
  dayan: endpoint('大雁塔', 'amap:poi:dayan', 34.2186, 108.9642),
  hotel: endpoint('西安钟楼饭店', 'amap:poi:bell-tower-hotel', 34.259, 108.942),
  museum: endpoint('陕西历史博物馆', 'amap:poi:shaanxi-museum', 34.2224, 108.9535),
  lunchTwo: endpoint('子午路张记肉夹馍（小寨店）', 'amap:poi:xiaozhai-lunch', 34.226, 108.953),
  wall: endpoint('西安城墙·永宁门', 'amap:poi:yongning-gate', 34.244, 108.9425),
};

function segment(
  segmentId: string,
  mode: TransportMode,
  from: FixtureEndpoint,
  to: FixtureEndpoint,
  duration: number,
  distance: number,
  path: Array<{ latitude: number; longitude: number }> = [],
) {
  return {
    segment_id: segmentId,
    mode,
    from_endpoint: from,
    to_endpoint: to,
    departure_at: null,
    arrival_at: null,
    duration_minutes: duration,
    distance_meters: distance,
    operator_name: null,
    service_number: null,
    line_name: null,
    cost_cny: null,
    path,
  };
}

function leg(
  id: string,
  mode: TransportMode,
  transportClass: TransportClass,
  duration: number,
  distance: number,
  segments: FixtureSegment[],
  micro = false,
) {
  const first = segments[0].from_endpoint;
  const last = segments.at(-1)!.to_endpoint;
  return {
    type: 'transport_leg',
    transport_leg_id: id,
    transport_class: transportClass,
    selected_mode: mode,
    from_endpoint: first,
    to_endpoint: last,
    departure_at: null,
    arrival_at: null,
    duration_minutes: duration,
    distance_meters: distance,
    total_cost_cny: null,
    transfer_count: Math.max(0, segments.length - 1),
    segments,
    booking_status: 'not_required',
    route_status: 'ready',
    mode_preference: { locked_mode: null, excluded_modes: [] },
    intent_explanations: [],
    evidence_basis: EVIDENCE,
    is_micro_transport: micro,
  };
}

const transportLegs = [
  leg('leg-terracotta-lunch', 'drive', 'flexible', 24, 9200, [
    segment('segment-terracotta-lunch', 'drive', points.terracotta, points.lunchOne, 24, 9200, [
      { latitude: 34.3848, longitude: 109.2785 },
      { latitude: 34.3812, longitude: 109.2541 },
      { latitude: 34.3764, longitude: 109.2312 },
      { latitude: 34.3725, longitude: 109.2137 },
    ]),
  ]),
  leg('leg-lunch-dayan', 'bus', 'public_transit', 72, 34400, [
    segment('segment-lunch-dayan', 'bus', points.lunchOne, points.dayan, 72, 34400, [
      { latitude: 34.3725, longitude: 109.2137 },
      { latitude: 34.335, longitude: 109.142 },
      { latitude: 34.278, longitude: 109.048 },
      { latitude: 34.2186, longitude: 108.9642 },
    ]),
  ]),
  leg('leg-dayan-hotel', 'taxi', 'flexible', 22, 7300, [
    segment('segment-dayan-hotel', 'taxi', points.dayan, points.hotel, 22, 7300),
  ]),
  leg('leg-hotel-museum', 'metro', 'public_transit', 31, 5800, [
    segment('segment-hotel-museum', 'metro', points.hotel, points.museum, 31, 5800, [
      { latitude: 34.259, longitude: 108.942 },
      { latitude: 34.249, longitude: 108.947 },
      { latitude: 34.236, longitude: 108.951 },
      { latitude: 34.2224, longitude: 108.9535 },
    ]),
  ]),
  leg('leg-museum-lunch', 'walk', 'flexible', 7, 520, [
    segment('segment-museum-lunch', 'walk', points.museum, points.lunchTwo, 7, 520, [
      { latitude: 34.2224, longitude: 108.9535 },
      { latitude: 34.2242, longitude: 108.9532 },
      { latitude: 34.226, longitude: 108.953 },
    ]),
  ], true),
  leg('leg-lunch-wall', 'bike', 'flexible', 16, 2600, [
    segment('segment-lunch-wall', 'bike', points.lunchTwo, points.wall, 16, 2600),
  ]),
];

function block(
  entryId: string,
  entityType: EntityType,
  entityId: string,
  entityKind: 'visit' | 'dining' | 'lodging' | 'transport',
  title: string,
  summary: string,
  time: string | null,
  options: {
    role?: ProjectionRole;
    nodeRole?: 'place' | 'movement' | 'arrival' | 'departure';
    mode?: TransportMode;
    duration?: string;
    price?: string;
  } = {},
) {
  return {
    entity_ref: ref(entityType, entityId),
    day_id: entryId.startsWith('d1-') ? 'day-1' : 'day-2',
    projection_role: options.role ?? 'full',
    entity_kind: entityKind,
    title,
    summary,
    details: {
      entry_id: entryId,
      display_title: title,
      node_summary: summary,
      node_role: options.nodeRole ?? (entityKind === 'transport' ? 'movement' : 'place'),
      transport_mode: options.mode ?? null,
      time_label: time,
      duration_label: options.duration ?? null,
      price_label: options.price ?? null,
      facts: [],
      notes: [],
      segment_lines: [],
    },
    citation_ids: [],
    evidence_basis: EVIDENCE,
  };
}

const dayOneBlocks = [
  block('d1-terracotta', 'visit_stop', 'visit-terracotta', 'visit', '秦始皇帝陵博物院（兵马俑）', '从一号坑的军阵开始，再细看陶俑的甲胄与神态。', '09:00', { duration: '建议 3 小时', price: '约 ¥120' }),
  block('d1-transfer-lunch', 'transport_leg', 'leg-terracotta-lunch', 'transport', '前往临潼城区用餐', '乘车前往午餐地点。', '12:20', { mode: 'drive', duration: '约 24 分钟' }),
  block('d1-lunch', 'dining_stop', 'dining-lintong', 'dining', '老白家水盆羊肉（临潼店）', '午餐安排水盆羊肉和陕西小菜。', '13:00', { duration: '约 1 小时', price: '人均约 ¥65' }),
  block('d1-transfer-dayan', 'transport_leg', 'leg-lunch-dayan', 'transport', '临潼前往大雁塔', '乘公交返回市区。', '14:10', { mode: 'bus', duration: '约 72 分钟' }),
  block('d1-dayan', 'visit_stop', 'visit-dayan', 'visit', '大雁塔', '傍晚前抵达，沿大慈恩寺遗址公园散步并登塔远眺。', '15:40', { duration: '建议 2 小时', price: '约 ¥40' }),
  block('d1-transfer-hotel', 'transport_leg', 'leg-dayan-hotel', 'transport', '返回钟楼住宿', '乘出租车前往酒店。', '18:20', { mode: 'taxi', duration: '约 22 分钟' }),
  block('d1-hotel', 'lodging_stay', 'stay-bell-tower', 'lodging', '西安钟楼饭店', '住在钟楼附近，晚间可以步行逛街。', '19:00', { role: 'check_in', nodeRole: 'arrival' }),
];

const dayTwoBlocks = [
  block('d2-hotel-out', 'lodging_stay', 'stay-bell-tower', 'lodging', '西安钟楼饭店', '退房后前往小寨。', '08:30', { role: 'check_out', nodeRole: 'departure' }),
  block('d2-transfer-museum', 'transport_leg', 'leg-hotel-museum', 'transport', '钟楼前往陕西历史博物馆', '乘地铁前往博物馆。', '08:40', { mode: 'metro', duration: '约 31 分钟' }),
  block('d2-museum', 'visit_stop', 'visit-shaanxi-museum', 'visit', '陕西历史博物馆', '以周秦汉唐文物为主线，预留充足时间看基本陈列。', '09:30', { duration: '建议 2.5 小时' }),
  block('d2-transfer-lunch', 'transport_leg', 'leg-museum-lunch', 'transport', '步行前往午餐', '从博物馆步行到小寨。', '12:10', { mode: 'walk', duration: '约 7 分钟' }),
  block('d2-lunch', 'dining_stop', 'dining-xiaozhai', 'dining', '子午路张记肉夹馍（小寨店）', '午餐吃肉夹馍、凉皮和冰峰。', '12:20', { duration: '约 50 分钟', price: '人均约 ¥35' }),
  block('d2-transfer-wall', 'transport_leg', 'leg-lunch-wall', 'transport', '前往永宁门', '骑行前往城墙南门。', '13:30', { mode: 'bike', duration: '约 16 分钟' }),
  block('d2-wall', 'visit_stop', 'visit-yongning-gate', 'visit', '西安城墙·永宁门', '从永宁门登城，沿城墙慢走，眺望城市中轴。', '14:00', { duration: '建议 2 小时', price: '约 ¥54' }),
];

export function xianDeliveryBundle(revision = 1) {
  const cost = {
    known_subtotal_cny: null,
    estimated_total_cny: null,
    priced_component_count: 0,
    budget_relevant_component_count: 0,
    coverage: 'none' as const,
    budget_cap_cny: null,
    budget_status: 'unknown' as const,
    llm_estimated_total_cny: null,
  };
  const places = [
    { ref: ref('visit_stop', 'visit-terracotta'), point: points.terracotta },
    { ref: ref('dining_stop', 'dining-lintong'), point: points.lunchOne },
    { ref: ref('visit_stop', 'visit-dayan'), point: points.dayan },
    { ref: ref('lodging_stay', 'stay-bell-tower'), point: points.hotel },
    { ref: ref('visit_stop', 'visit-shaanxi-museum'), point: points.museum },
    { ref: ref('dining_stop', 'dining-xiaozhai'), point: points.lunchTwo },
    { ref: ref('visit_stop', 'visit-yongning-gate'), point: points.wall },
  ];

  return {
    manifest: {
      contract_version: DELIVERY_BUNDLE_CONTRACT_VERSION,
      run_id: 'run-A',
      generation_id: 'generation-A',
      bundle_id: `bundle-${revision}`,
      workspace_revision: revision,
      fact_data_revision: revision,
      weather_data_revision: revision,
      created_at: '2026-10-25T08:00:00Z',
    },
    workspace: {
      contract_version: TRIP_WORKSPACE_CONTRACT_VERSION,
      run_id: 'run-A',
      generation_id: 'generation-A',
      workspace_revision: revision,
      itinerary: {
        itinerary_id: 'itinerary-xian',
        title: '西安两日 · 秦唐风物',
        destination_ids: [XI],
        duration_days: 2,
        day_plans: [
          { day_id: 'day-1', day: 1, date: '2026-11-01', destination_id: XI, theme: '秦唐遗韵 · 临潼与雁塔', timeline: dayOneBlocks.map((item) => ({ entry_id: item.details.entry_id, entity_type: item.entity_ref.entity_type, entity_id: item.entity_ref.entity_id, projection_role: item.projection_role })), estimated_cost_cny: null },
          { day_id: 'day-2', day: 2, date: '2026-11-02', destination_id: XI, theme: '城中慢游 · 博物馆与城墙', timeline: dayTwoBlocks.map((item) => ({ entry_id: item.details.entry_id, entity_type: item.entity_ref.entity_type, entity_id: item.entity_ref.entity_id, projection_role: item.projection_role })), estimated_cost_cny: null },
        ],
        visit_stops: [
          { type: 'visit_stop', item_id: 'visit-terracotta', day_id: 'day-1', place_id: points.terracotta.place_id!, name: points.terracotta.name, address: '陕西省西安市临潼区秦陵北路', latitude: points.terracotta.latitude, longitude: points.terracotta.longitude, planned_start: '2026-11-01T09:00:00+08:00', planned_end: '2026-11-01T12:00:00+08:00', duration_minutes: 180, estimated_cost_cny: 120, selection_reason: '把兵马俑放在第一天体力充足的上午。', visit_type: 'attraction', opening_window: '08:30–17:00', reservation_required: true, visit_highlights: ['一号坑军阵', '陶俑细节'], intent_explanations: [], evidence_basis: EVIDENCE },
          { type: 'visit_stop', item_id: 'visit-dayan', day_id: 'day-1', place_id: points.dayan.place_id!, name: points.dayan.name, address: '陕西省西安市雁塔区雁塔南路', latitude: points.dayan.latitude, longitude: points.dayan.longitude, planned_start: '2026-11-01T15:40:00+08:00', planned_end: '2026-11-01T17:40:00+08:00', duration_minutes: 120, estimated_cost_cny: 40, selection_reason: '下午返回市区后衔接大雁塔。', visit_type: 'culture', opening_window: '08:00–17:30', reservation_required: null, visit_highlights: ['大慈恩寺', '雁塔北广场'], intent_explanations: [], evidence_basis: EVIDENCE },
          { type: 'visit_stop', item_id: 'visit-shaanxi-museum', day_id: 'day-2', place_id: points.museum.place_id!, name: points.museum.name, address: '陕西省西安市雁塔区小寨东路', latitude: points.museum.latitude, longitude: points.museum.longitude, planned_start: '2026-11-02T09:30:00+08:00', planned_end: '2026-11-02T12:00:00+08:00', duration_minutes: 150, estimated_cost_cny: null, selection_reason: '第二天用上午完整参观基本陈列。', visit_type: 'culture', opening_window: '09:00–17:30', reservation_required: true, visit_highlights: ['唐代壁画', '周秦汉唐文物'], intent_explanations: [], evidence_basis: EVIDENCE },
          { type: 'visit_stop', item_id: 'visit-yongning-gate', day_id: 'day-2', place_id: points.wall.place_id!, name: points.wall.name, address: '陕西省西安市碑林区南大街', latitude: points.wall.latitude, longitude: points.wall.longitude, planned_start: '2026-11-02T14:00:00+08:00', planned_end: '2026-11-02T16:00:00+08:00', duration_minutes: 120, estimated_cost_cny: 54, selection_reason: '午后从南门登城，路线直观。', visit_type: 'attraction', opening_window: '08:00–22:00', reservation_required: null, visit_highlights: ['永宁门城楼', '城墙漫步'], intent_explanations: [], evidence_basis: EVIDENCE },
        ],
        dining_stops: [
          { type: 'dining_stop', item_id: 'dining-lintong', day_id: 'day-1', place_id: points.lunchOne.place_id!, name: points.lunchOne.name, address: '陕西省西安市临潼区人民路', latitude: points.lunchOne.latitude, longitude: points.lunchOne.longitude, planned_start: '2026-11-01T13:00:00+08:00', planned_end: '2026-11-01T14:00:00+08:00', duration_minutes: 60, estimated_cost_cny: 65, selection_reason: '上午游览后在临潼城区用餐。', meal_type: 'lunch', cuisine_types: ['陕西菜'], average_spend_cny: 65, recommended_dishes: ['水盆羊肉', '月牙饼'], reservation_required: null, opening_window: '10:00–21:00', dining_reminders: [], intent_explanations: [], evidence_basis: EVIDENCE },
          { type: 'dining_stop', item_id: 'dining-xiaozhai', day_id: 'day-2', place_id: points.lunchTwo.place_id!, name: points.lunchTwo.name, address: '陕西省西安市雁塔区小寨西路', latitude: points.lunchTwo.latitude, longitude: points.lunchTwo.longitude, planned_start: '2026-11-02T12:20:00+08:00', planned_end: '2026-11-02T13:10:00+08:00', duration_minutes: 50, estimated_cost_cny: 35, selection_reason: '博物馆参观后步行可达。', meal_type: 'lunch', cuisine_types: ['陕西小吃'], average_spend_cny: 35, recommended_dishes: ['肉夹馍', '凉皮'], reservation_required: false, opening_window: '08:00–21:30', dining_reminders: [], intent_explanations: [], evidence_basis: EVIDENCE },
        ],
        lodging_stays: [
          { type: 'lodging_stay', stay_id: 'stay-bell-tower', place_id: points.hotel.place_id!, name: points.hotel.name, check_in_date: '2026-11-01', check_out_date: '2026-11-02', check_in_time: '19:00', check_out_time: '08:30', nights: 1, room_type: '双床房', nightly_price_cny: 520, total_price_cny: 520, price_kind: 'reference_estimate', availability_status: 'needs_confirmation', address: '陕西省西安市碑林区南大街', selection_reason: '钟楼附近便于晚间散步和第二天出发。', intent_explanations: [], evidence_basis: EVIDENCE },
        ],
        transport_legs: transportLegs,
        custom_blocks: [],
        cost_summary: cost,
        highlights: ['兵马俑与大雁塔串成第一天主线', '第二天集中在市区，减少折返'],
        important_notes: [],
      },
      selection_slots: [],
      weather_proposal_decisions: [],
      weather_adjustments: [],
    },
    report_projection: {
      source_workspace_revision: revision,
      source_fact_data_revision: revision,
      source_weather_data_revision: revision,
      status: 'ready',
      document: {
        title: '离线旅行报告',
        overview: '用两天时间串起临潼、雁塔与西安古城。',
        destinations: [{ destination_id: XI, display_name: '西安' }],
        duration_days: 2,
        cost_summary: cost,
        cost_coverage_statement: null,
        days: [
          { day_id: 'day-1', day: 1, date: '2026-11-01', destination_id: XI, destination_name: '西安', theme: '秦唐遗韵 · 临潼与雁塔', blocks: dayOneBlocks },
          { day_id: 'day-2', day: 2, date: '2026-11-02', destination_id: XI, destination_name: '西安', theme: '城中慢游 · 博物馆与城墙', blocks: dayTwoBlocks },
        ],
        selections: [],
        weather: [],
        highlights: ['秦唐文化', '古城漫步'],
        important_notes: [],
      },
      citations: [],
      generated_at: '2026-10-25T08:00:00Z',
    },
    map_projection: {
      source_workspace_revision: revision,
      content: {
        places: places.map(({ ref: entityRef, point }) => ({ entity_ref: entityRef, name: point.name, place_id: point.place_id!, latitude: point.latitude, longitude: point.longitude, citation_ids: [] })),
        routes: transportLegs.map((item) => ({ entity_ref: ref('transport_leg', item.transport_leg_id), transport_class: item.transport_class, selected_mode: item.selected_mode, route_status: item.route_status, from_endpoint: item.from_endpoint, to_endpoint: item.to_endpoint, segments: item.segments, citation_ids: [] })),
      },
    },
    source_index: { source_fact_data_revision: revision, content: { citations: [] } },
    provider_environment: { sandbox_note: null },
  };
}

export function xianMixedTransportBundle() {
  const bundle = structuredClone(xianDeliveryBundle());
  const beijingAirport = endpoint('北京首都国际机场', 'airport:beijing-capital', 40.0801, 116.5846);
  const xianAirport = endpoint('西安咸阳国际机场', 'airport:xian-xianyang', 34.4471, 108.7517);
  const xianNorth = endpoint('西安北站', 'station:xian-north', 34.3762, 108.9397);
  const beijingWest = endpoint('北京西站', 'station:beijing-west', 39.8955, 116.3216);
  const extraLegs = [
    leg('leg-flight-demo', 'flight', 'long_distance', 125, 910000, [
      segment('segment-flight-demo', 'flight', beijingAirport, xianAirport, 125, 910000, [
        { latitude: beijingAirport.latitude, longitude: beijingAirport.longitude },
        { latitude: 37.4, longitude: 112.1 },
        { latitude: xianAirport.latitude, longitude: xianAirport.longitude },
      ]),
    ]),
    leg('leg-ride-demo', 'ride_hailing', 'flexible', 55, 45000, [
      segment('segment-ride-demo', 'drive', xianAirport, points.terracotta, 55, 45000, [
        { latitude: xianAirport.latitude, longitude: xianAirport.longitude },
        { latitude: 34.426, longitude: 108.88 },
        { latitude: 34.405, longitude: 109.08 },
        { latitude: points.terracotta.latitude, longitude: points.terracotta.longitude },
      ]),
    ]),
    leg('leg-station-taxi-demo', 'taxi', 'flexible', 30, 16000, [
      segment('segment-station-taxi-demo', 'drive', points.wall, xianNorth, 30, 16000, [
        { latitude: points.wall.latitude, longitude: points.wall.longitude },
        { latitude: 34.29, longitude: 108.95 },
        { latitude: 34.34, longitude: 108.94 },
        { latitude: xianNorth.latitude, longitude: xianNorth.longitude },
      ]),
    ]),
    leg('leg-rail-demo', 'high_speed_rail', 'long_distance', 300, 1210000, [
      segment('segment-rail-demo', 'high_speed_rail', xianNorth, beijingWest, 300, 1210000, [
        { latitude: xianNorth.latitude, longitude: xianNorth.longitude },
        { latitude: 35.05, longitude: 113.6 },
        { latitude: 38.04, longitude: 114.5 },
        { latitude: beijingWest.latitude, longitude: beijingWest.longitude },
      ]),
    ]),
  ];
  bundle.workspace.itinerary.transport_legs.push(...extraLegs);
  bundle.map_projection.content.routes.push(...extraLegs.map((item) => ({
    entity_ref: ref('transport_leg', item.transport_leg_id),
    transport_class: item.transport_class,
    selected_mode: item.selected_mode,
    route_status: item.route_status,
    from_endpoint: item.from_endpoint,
    to_endpoint: item.to_endpoint,
    segments: item.segments,
    citation_ids: [],
  })));

  const dayan = bundle.workspace.itinerary.visit_stops.find((place) => place.item_id === 'visit-dayan')!;
  const duplicate = {
    ...dayan,
    item_id: 'visit-dayan-duplicate',
    place_id: 'amap:poi:dayan-guide',
    name: '大雁塔文化讲解',
    planned_start: '2026-11-01T17:40:00+08:00',
    planned_end: '2026-11-01T18:20:00+08:00',
    duration_minutes: 40,
  };
  bundle.workspace.itinerary.visit_stops.push(duplicate);
  bundle.map_projection.content.places.push({
    entity_ref: ref('visit_stop', duplicate.item_id),
    name: duplicate.name,
    place_id: duplicate.place_id,
    latitude: duplicate.latitude,
    longitude: duplicate.longitude,
    citation_ids: [],
  });

  const reportDays = bundle.report_projection.document.days;
  reportDays[0].blocks.unshift(
    block('d1-flight-demo', 'transport_leg', 'leg-flight-demo', 'transport', '飞往西安', '从北京首都国际机场飞往西安咸阳国际机场。', '05:30', { mode: 'flight', duration: '约 2 小时 5 分钟' }),
    block('d1-ride-demo', 'transport_leg', 'leg-ride-demo', 'transport', '前往兵马俑', '抵达后乘网约车前往秦始皇帝陵博物院。', '08:00', { mode: 'ride_hailing', duration: '约 55 分钟' }),
  );
  const hotelTransferIndex = reportDays[0].blocks.findIndex((item) => item.details.entry_id === 'd1-transfer-hotel');
  reportDays[0].blocks.splice(hotelTransferIndex, 0, block(
    'd1-dayan-guide', 'visit_stop', 'visit-dayan-duplicate', 'visit', '大雁塔文化讲解', '在同一地点继续参加文化讲解，无需再次移动。', '17:40', { duration: '约 40 分钟' },
  ));
  reportDays[1].blocks.push(
    block('d2-station-taxi-demo', 'transport_leg', 'leg-station-taxi-demo', 'transport', '前往西安北站', '游览结束后乘出租车前往西安北站。', '16:20', { mode: 'taxi', duration: '约 30 分钟' }),
    block('d2-rail-demo', 'transport_leg', 'leg-rail-demo', 'transport', '乘高铁返京', '从西安北站乘高铁返回北京西站。', '17:10', { mode: 'high_speed_rail', duration: '约 5 小时' }),
  );
  reportDays.forEach((day, index) => {
    bundle.workspace.itinerary.day_plans[index].timeline = day.blocks.map((item) => ({
      entry_id: item.details.entry_id,
      entity_type: item.entity_ref.entity_type,
      entity_id: item.entity_ref.entity_id,
      projection_role: item.projection_role,
    }));
  });
  return bundle;
}
