export type WeatherIconKind = 'clear' | 'partly' | 'cloudy' | 'rain' | 'drizzle' | 'thunder' | 'snow' | 'fog' | 'wind' | 'unknown';
export function isRainy(icon: WeatherIconKind): boolean {
    return icon === 'rain' || icon === 'drizzle' || icon === 'thunder';
}
export function weatherIconForLabel(label: string | null): WeatherIconKind {
    if (!label)
        return 'unknown';
    const normalized = label.toLowerCase();
    if (/雷暴|雷雨|thunder|lightning/.test(normalized))
        return 'thunder';
    if (/小雨|毛毛雨|drizzle/.test(normalized))
        return 'drizzle';
    if (/降雨|阵雨|暴雨|雨|rain/.test(normalized))
        return 'rain';
    if (/降雪|雨夹雪|雪|snow/.test(normalized))
        return 'snow';
    if (/雾|霾|fog|haze/.test(normalized))
        return 'fog';
    if (/大风|强风|wind/.test(normalized))
        return 'wind';
    if (/多云|partly/.test(normalized))
        return 'partly';
    if (/阴|cloud/.test(normalized))
        return 'cloudy';
    if (/晴|sun|clear/.test(normalized))
        return 'clear';
    return 'unknown';
}
