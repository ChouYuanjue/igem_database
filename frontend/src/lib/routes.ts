import { useCallback, useEffect, useState } from 'react'
import type { View } from './entities'

/**
 * 首页地图上的一次检索。让它进 URL 是为了让**浏览器后退退掉这次检索**,
 * 而不是因为 `/` 是标签页的第一条记录就直接退出网站。
 *
 * 形状与后端契约一一对应: 关键词检索只有 `query`; 通路检索把 composer
 * 交给 API 的那串 token 原样带来(`start`/`end`/`via`), 服务端本来就能解析
 * id、裸 ChEBI 号或化合物名, 所以从 URL 重放出来的结果与手动跑一次完全一致。
 */
export type MapSearchRoute = {
  mode: 'enzyme' | 'pathway'
  /** 关键词检索的词。通路检索恒为空串 —— 一条链不是一个词能描述的。 */
  query: string
  start: string
  end: string
  via: string[]
}

export type AppRoute = {
  view: Exclude<View, 'structure'>
  enzymeId?: string
  query?: string
  blast?: boolean
  /**
   * 只在 `view === 'home'` 时有意义。**三态缺一不可**:
   * - `undefined` 不是首页 —— 无信号, 消费方什么都别动;
   * - `null` 首页且没有任何检索参数 —— 清掉检索现场;
   * - 有值 —— 按这个规格跑检索。
   *
   * 把 `undefined` 并进 `null` 会立刻打回「打开酶详情页顺手清空地图检索结果」
   * 那个 bug: 从 `/?q=x` 进 `/enzymes/X` 时规格会凭空变成「该清空」。
   */
  mapSearch?: MapSearchRoute | null
}

/** `?q=` / `mode` / `start` / `end` / `via` → 检索规格。一个都没有则是 `null`。 */
function parseMapSearch(params: URLSearchParams): MapSearchRoute | null {
  const query = params.get('q') ?? ''
  const start = params.get('start') ?? ''
  const end = params.get('end') ?? ''
  const via = params.getAll('via').filter((token) => token !== '')
  const wantsPathway = params.get('mode') === 'pathway'
  // 没有词可检的 `?mode=enzyme` 不是检索, 归一化成裸首页, 免得 URL 与状态各说各话。
  if (!query && !wantsPathway && !start && !end && via.length === 0) return null
  // `mode` 由有没有关键词推出来, 不单独存 —— 这样 `routeUrl(parseRoute(url))`
  // 一定等于规范形式, `syncRoute` 不会每次 popstate 都 replaceState 一遍。
  return { mode: query ? 'enzyme' : 'pathway', query, start, end, via }
}

/** 固定顺序 `q, mode, start, end, via` —— 顺序不稳会让上一条的规范化反复触发。 */
function serializeMapSearch(spec: MapSearchRoute, params: URLSearchParams) {
  if (spec.query) params.set('q', spec.query)
  params.set('mode', spec.mode)
  if (spec.start) params.set('start', spec.start)
  if (spec.end) params.set('end', spec.end)
  // `via` 用重复参数而不是逗号拼接: 这里的 token 可能是没解析出来的原始文本,
  // 而真实化合物名里就有逗号(实测标签 `2-cis,6-cis-farnesyl diphosphate(3−)`)。
  spec.via.filter((token) => token !== '').forEach((token) => params.append('via', token))
}

export function parseRoute(url: URL): AppRoute {
  const path = url.pathname.replace(/\/+$/, '') || '/'
  if (path === '/') return { view: 'home', mapSearch: parseMapSearch(url.searchParams) }
  if (path === '/downloads') return { view: 'downloads' }
  if (path === '/search') {
    return { view: 'search', query: url.searchParams.get('q') ?? '', blast: url.searchParams.get('mode') === 'blast' }
  }
  const match = /^\/enzymes\/([^/]+)$/.exec(path)
  if (match) {
    try {
      const enzymeId = decodeURIComponent(match[1])
      if (enzymeId.trim()) return { view: 'enzyme', enzymeId }
    } catch {
      return { view: 'home' }
    }
  }
  return { view: 'home' }
}

export function routeUrl(route: AppRoute): string {
  if (route.view === 'downloads') return '/downloads'
  if (route.view === 'enzyme' && route.enzymeId) return `/enzymes/${encodeURIComponent(route.enzymeId)}`
  if (route.view === 'search') {
    const params = new URLSearchParams()
    if (route.query) params.set('q', route.query)
    if (route.blast) params.set('mode', 'blast')
    const search = params.toString()
    return `/search${search ? `?${search}` : ''}`
  }
  if (route.view === 'home' && route.mapSearch) {
    const params = new URLSearchParams()
    serializeMapSearch(route.mapSearch, params)
    const search = params.toString()
    return `/${search ? `?${search}` : ''}`
  }
  // 没有检索参数的首页必须**仍然**是裸 `'/'` —— `resetHome`、`goTo('home')`
  // 全都靠它表达「回到干净的浏览图」。
  return '/'
}

/**
 * 本应用在 `history.state` 里存一个「我们自己 push 了几层」的下标, 用来判断
 * 还有没有可退的应用内历史。**不要换成 push 时 +1 / popstate 时 -1 的计数器**:
 * `popstate` 对**前进**也一样触发, 「退一步再进一步」会把计数减到 0,
 * 明明后面还有条目却被判成「退不了」。下标存在 state 里则前进后退都对 ——
 * popstate 时重读一次就是权威值。
 */
type RouteHistoryState = { atlasIndex?: number }

function currentIndex(): number {
  const state = window.history.state as RouteHistoryState | null
  return typeof state?.atlasIndex === 'number' ? state.atlasIndex : 0
}

export function useAppRoute() {
  const [route, setRoute] = useState(() => parseRoute(new URL(window.location.href)))
  const [historyIndex, setHistoryIndex] = useState(currentIndex)

  useEffect(() => {
    const syncRoute = () => {
      const next = parseRoute(new URL(window.location.href))
      const canonical = routeUrl(next)
      if (`${window.location.pathname}${window.location.search}` !== canonical) {
        // 这次原地规范化不是一次导航, 下标必须**原样带过去**, 不能写 null 抹掉。
        window.history.replaceState({ atlasIndex: currentIndex() }, '', canonical)
      }
      setRoute(next)
      setHistoryIndex(currentIndex())
    }
    syncRoute()
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  const navigate = useCallback((next: AppRoute, replace = false) => {
    const target = routeUrl(next)
    if (`${window.location.pathname}${window.location.search}` !== target) {
      const index = currentIndex()
      if (replace) {
        // replace 不新增条目, 所以下标不动 —— 「能不能退」不该因此改变。
        window.history.replaceState({ atlasIndex: index }, '', target)
      } else {
        window.history.pushState({ atlasIndex: index + 1 }, '', target)
        setHistoryIndex(index + 1)
      }
    }
    setRoute(parseRoute(new URL(target, window.location.origin)))
  }, [])

  /** 退回上一条应用内记录。返回 false 表示栈里没有可退的项, 调用方自行兜底。 */
  const goBack = useCallback(() => {
    if (currentIndex() <= 0) return false
    window.history.back()
    return true
  }, [])

  return { route, navigate, goBack, canGoBack: historyIndex > 0 }
}
