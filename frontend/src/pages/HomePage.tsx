import { CompoundGraphHome } from '../graphExperience'
import type { BlastSession } from '../api'
import type { Entity } from '../types'
import type { MapSearchRoute } from '../lib/routes'

export function HomePage({
  hidden,
  resetNonce,
  queueCount,
  entityCount: _entityCount,
  nodeCount: _nodeCount,
  edgeCount: _edgeCount,
  downloadedItems: _downloadedItems,
  onOpenSearch,
  onOpenDownloads,
  onOpenEnzyme,
  onOpenBlast,
  onOpenBlastTable,
  onToggleQueue,
  onQueueMany,
  openRecord: _openRecord,
  isQueued,
  mapSearch,
  mapSearchNonce,
  onMapSearch,
  blastSession,
  autoBlastScope,
  onAutoBlastScopeConsumed,
  onResetHome,
  searchSet,
  onSearchSetChange,
}: {
  /** The map stays mounted across routes; this only takes it out of the layout. */
  hidden?: boolean
  /** Bumped by App's `resetHome`; the map watches it to drop its own scope state. */
  resetNonce?: number
  queueCount: number
  entityCount: number
  nodeCount: number
  edgeCount: number
  downloadedItems: Entity[]
  onOpenSearch: (query?: string) => void
  onOpenDownloads: () => void
  onOpenEnzyme: (id: string) => void
  onOpenBlast: () => void
  onOpenBlastTable: () => void
  onToggleQueue: (entry: string | Entity) => void
  /** 批量入队（合并抽屉的「Queue all」）。 */
  onQueueMany: (entries: Entity[]) => void
  openRecord: (entity: Entity) => void
  isQueued: (id: string) => boolean
  /** URL 上的检索规格 (`undefined` = 不在首页, 无信号; `null` = 裸首页)。 */
  mapSearch?: MapSearchRoute | null
  /** 同一个规格再提交一次时递增; 只由它触发重跑。 */
  mapSearchNonce?: number
  /** 地图请求把一次检索写进 URL (App 负责导航, 地图只消费结果)。 */
  onMapSearch?: (spec: MapSearchRoute | null) => void
  /** Last completed BLAST run; lets the map render the hit enzymes as a scope subgraph. */
  blastSession?: BlastSession | null
  autoBlastScope?: { sessionId: number; nonce: number } | null
  onAutoBlastScopeConsumed?: () => void
  /** Brand click → reset any app-wide search state and head back to home. */
  onResetHome?: () => void
  /** 搜索集（检索范围）。空数组 = 全部。 */
  searchSet: string[]
  onSearchSetChange: (next: string[]) => void
}) {
  return (
    <CompoundGraphHome
      hidden={hidden}
      resetNonce={resetNonce}
      onOpenSearch={onOpenSearch}
      onOpenDownloads={onOpenDownloads}
      onOpenEnzyme={onOpenEnzyme}
      onOpenBlast={onOpenBlast}
      onOpenBlastTable={onOpenBlastTable}
      onToggleQueue={onToggleQueue}
      onQueueMany={onQueueMany}
      isQueued={isQueued}
      queueCount={queueCount}
      mapSearch={mapSearch}
      mapSearchNonce={mapSearchNonce}
      onMapSearch={onMapSearch}
      blastSession={blastSession}
      autoBlastScope={autoBlastScope}
      onAutoBlastScopeConsumed={onAutoBlastScopeConsumed}
      onResetHome={onResetHome}
      searchSet={searchSet}
      onSearchSetChange={onSearchSetChange}
    />
  )
}
