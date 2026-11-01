import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DELIVERY_BUNDLE_CONTRACT_VERSION } from './delivery';
import { TRIP_WORKSPACE_CONTRACT_VERSION } from './workspace';
import { WEATHER_SNAPSHOT_CONTRACT_VERSION } from './weather';

// 前后端按字面量比对契约版本：任何一侧单独升级都会让真实交付被判废，
// 所以这里直接读取后端常量，而不是在前端再抄一份固定值。
function literalVersion(source: string, constant: string): string {
  const match = source.match(new RegExp(`(?:export )?const ${constant} = ['"]([^'"]+)['"]`));
  if (!match) {
    throw new Error(`源码中缺少 ${constant}`);
  }
  return match[1];
}

function backendVersion(file: string, constant: string): string {
  const source = readFileSync(
    new URL(`../../../../../backend/travel_agent/${file}`, import.meta.url),
    'utf8',
  );
  const match = source.match(new RegExp(`^${constant} = "([^"]+)"`, 'm'));
  if (!match) {
    throw new Error(`后端 ${file} 缺少 ${constant}`);
  }
  return match[1];
}

const MIRRORED_VERSIONS = [
  {
    name: '交付 Bundle',
    file: 'planning/delivery/bundle.py',
    constant: 'DELIVERY_BUNDLE_CONTRACT_VERSION',
    frontend: DELIVERY_BUNDLE_CONTRACT_VERSION,
  },
  {
    name: '旅行工作台',
    file: 'planning/workspace.py',
    constant: 'TRIP_WORKSPACE_CONTRACT_VERSION',
    frontend: TRIP_WORKSPACE_CONTRACT_VERSION,
  },
  {
    name: '天气快照',
    file: 'planning/weather/models.py',
    constant: 'WEATHER_SNAPSHOT_CONTRACT_VERSION',
    frontend: WEATHER_SNAPSHOT_CONTRACT_VERSION,
  },
];

describe('契约版本镜像', () => {
  for (const { name, file, constant, frontend } of MIRRORED_VERSIONS) {
    it(`${name}版本与后端一致`, () => {
      expect(backendVersion(file, constant)).toBe(frontend);
    });
  }

  it('e2e 会话夹具沿用同一版本', () => {
    const fixture = readFileSync(
      new URL('../../../../e2e/fixtures/xianBundle.ts', import.meta.url),
      'utf8',
    );
    expect(literalVersion(fixture, 'DELIVERY_BUNDLE_CONTRACT_VERSION')).toBe(
      DELIVERY_BUNDLE_CONTRACT_VERSION,
    );
    expect(literalVersion(fixture, 'TRIP_WORKSPACE_CONTRACT_VERSION')).toBe(
      TRIP_WORKSPACE_CONTRACT_VERSION,
    );
  });
});
