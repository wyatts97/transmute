import { useEffect, useRef, useState } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { FaArrowUpRightFromSquare, FaChartBar, FaChevronDown, FaGear, FaRightFromBracket, FaUser, FaUsers } from 'react-icons/fa6'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../AuthContext'
import { useTheme } from '../ThemeContext'
import { api } from '../utils/api'
import { getCapabilities, type Capabilities } from '../utils/encoding'

const navClass = ({ isActive }: { isActive: boolean }) =>
  `rounded-md px-2.5 py-1.5 text-xs transition ${isActive ? 'bg-text/10 text-text' : 'text-text-muted hover:text-text'}`

const menuItemClass = ({ isActive }: { isActive: boolean }) =>
  `flex w-full items-center gap-3 rounded-md px-3 py-2 text-xs transition ${isActive ? 'bg-text/10 text-text' : 'text-text-muted hover:bg-text/5 hover:text-text'}`

/** "Mesa Gallium driver … (radeonsi, renoir, …)" → "radeonsi" */
function shortDriver(driver: string | null): string | null {
  if (!driver) return null
  const match = driver.match(/\(([^,)]+)/)
  return match ? match[1].trim() : driver.split(' ')[0]
}

function HardwareChip() {
  const { t } = useTranslation()
  const [caps, setCaps] = useState<Capabilities | null>(null)
  useEffect(() => {
    getCapabilities().then(setCaps).catch(() => {})
  }, [])
  if (!caps) return null
  const gpu = caps.hardware.encoders.length > 0
  const label = gpu
    ? ['vaapi', shortDriver(caps.hardware.driver)].filter(Boolean).join(' · ')
    : t('nav.cpuOnly')
  const detail = gpu ? t('nav.gpuEncoders', { encoders: caps.hardware.encoders.join(', ') }) : t('nav.noGpu')
  return (
    <span
      className={`hidden rounded-full border px-2 py-0.5 font-mono text-[11px] sm:inline ${gpu ? 'border-primary/30 text-primary' : 'border-text/15 text-text-muted'}`}
      title={detail}
      aria-label={detail}
    >
      {label}
    </span>
  )
}

function Header() {
  const { keepOriginals } = useTheme()
  const { user, isAdmin, logout } = useAuth()
  const { t } = useTranslation()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }

    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [])

  return (
    <header className="border-b border-text/10 bg-surface-light">
      <nav className="flex h-12 items-center gap-4 px-3 sm:px-4">
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-on-primary">
            <svg viewBox="284 186 632 828" className="h-3.5 w-3.5" fill="currentColor" aria-label={t('nav.logo')}>
              <path
                fillRule="evenodd"
                d="m730.08 186c9.9844 0 18 8.0625 18 18v72c0 9.9375-8.0156 18-18 18h-18v193.92l172.87 363.05c36.047 75.656-19.125 163.03-102.89 163.03h-367.92c-83.766 0-138.94-87.375-102.94-163.03l172.87-363.05v-193.92h-18c-9.9375 0-18-8.0625-18-18v-72c0-9.9375 8.0625-18 18-18zm-225.32 426-128.53 269.95c-13.266 27.844 7.0312 60.047 37.922 60.047h367.92c30.844 0 51.188-32.203 37.922-60.047l-128.53-269.95z"
              />
            </svg>
          </span>
          <span className="font-mono text-sm font-medium lowercase text-text">{t('app.name')}</span>
        </Link>

        <div className="flex min-w-0 items-center gap-0.5 overflow-x-auto">
          <NavLink to="/" end className={navClass}>{t('nav.convert')}</NavLink>
          {keepOriginals && <NavLink to="/files" className={navClass}>{t('nav.files')}</NavLink>}
          <NavLink to="/history" className={navClass}>{t('nav.history')}</NavLink>
          <NavLink to="/presets" className={navClass}>{t('nav.presets')}</NavLink>
          <a
            href={api.url('/api/docs')}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs text-text-muted transition hover:text-text"
          >
            {t('nav.api')} <FaArrowUpRightFromSquare className="text-[9px]" />
          </a>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <HardwareChip />
          <div className="relative" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen(open => !open)}
              className="flex items-center gap-2 rounded-md border border-text/15 px-2.5 py-1 text-xs text-text transition hover:border-text/30"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              aria-label={t('menu.openAccountMenu')}
            >
              <FaUser className="text-[11px] text-text-muted" />
              <span className="hidden max-w-28 truncate sm:inline">{user?.username}</span>
              <FaChevronDown className={`text-[9px] text-text-muted transition-transform duration-200 ${menuOpen ? 'rotate-180' : ''}`} />
            </button>

            {menuOpen && (
              <div className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-lg border border-text/10 bg-surface-light shadow-xl">
                <div className="border-b border-text/10 px-4 py-3">
                  <p className="truncate text-sm text-text">{user?.username}</p>
                  <p className="mt-0.5 font-mono text-[11px] text-text-muted">{user?.role}</p>
                </div>
                <div className="p-1.5">
                  {!user?.is_guest && (
                    <>
                      <NavLink to="/account" onClick={() => setMenuOpen(false)} className={menuItemClass}>
                        <FaUser className="text-xs" />
                        {t('menu.myAccount')}
                      </NavLink>
                      <NavLink to="/settings" onClick={() => setMenuOpen(false)} className={menuItemClass}>
                        <FaGear className="text-xs" />
                        {t('menu.settings')}
                      </NavLink>
                      {isAdmin && (
                        <>
                          <NavLink to="/admin/users" onClick={() => setMenuOpen(false)} className={menuItemClass}>
                            <FaUsers className="text-xs" />
                            {t('menu.userManagement')}
                          </NavLink>
                          <NavLink to="/admin/stats" onClick={() => setMenuOpen(false)} className={menuItemClass}>
                            <FaChartBar className="text-xs" />
                            {t('menu.stats')}
                          </NavLink>
                        </>
                      )}
                    </>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      logout()
                    }}
                    className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-xs text-text-muted transition hover:bg-text/5 hover:text-text"
                  >
                    <FaRightFromBracket className="text-xs" />
                    {t('menu.signOut')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </nav>
    </header>
  )
}

export default Header
