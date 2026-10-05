type AtlasBrandProps = {
  onActivate: () => void
  title?: string
  ariaLabel?: string
  className?: string
}

export function AtlasBrand({
  onActivate,
  title = 'Back to the Atlas home map',
  ariaLabel = 'Atlas EDGE home',
  className = '',
}: AtlasBrandProps) {
  return (
    <div className="atlas-brand-zone">
      <button
        type="button"
        className={`atlas-brand ${className}`.trim()}
        onClick={onActivate}
        title={title}
        aria-label={ariaLabel}
      >
        <span className="atlas-logo">
          <img className="atlas-logo-mark" src="/database/starase-atlas-logo.png" alt="" />
        </span>
        <span className="atlas-brand-copy">
          <strong>Atlas EDGE</strong>
          <small>
            <b>E</b>nzyme <b>D</b>ataset and <b>G</b>raph <b>E</b>xplorer
          </small>
        </span>
      </button>
      <a className="atlas-suite-link" href="/" aria-label="Open Atlas COMPASS">
        COMPASS <span aria-hidden="true">↗</span>
      </a>
    </div>
  )
}
