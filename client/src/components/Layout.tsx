import type { ReactNode } from 'react'
import type { DisplayInfo, HealthResponse } from '../lib/api'
import { Icon, type IconName } from './Icon'

export type TabId = 'dashboard' | 'queue' | 'settings' | 'history'

interface LayoutProps {
  activeTab: TabId
  onTabChange: (tab: TabId) => void
  display: DisplayInfo | null
  health: HealthResponse | null
  queueCount: number
  authRequired: boolean
  onLogout: () => void
  children: ReactNode
}

const TABS: { id: TabId; label: string; icon: IconName }[] = [
  { id: 'dashboard', label: 'Tableau de bord', icon: 'home' },
  { id: 'queue', label: 'File d’attente', icon: 'image' },
  { id: 'history', label: 'Historique', icon: 'history' },
  { id: 'settings', label: 'Paramètres', icon: 'settings' },
]

export function Layout({ activeTab, onTabChange, display, health, queueCount, authRequired, onLogout, children }: LayoutProps) {
  return (
    <div className="min-h-screen">
      <a href="#main-content" className="studio-skip-link bento-button bento-button-primary">Aller au contenu</a>
      <header className="studio-header">
        <div className="studio-header-inner">
          <div className="studio-brand"><span className="studio-brand-mark" aria-hidden="true" />Inky Studio</div>
          <nav className="studio-nav" aria-label="Sections principales">
            {TABS.map((tab) => (
              <button key={tab.id} type="button" onClick={() => onTabChange(tab.id)} className="studio-nav-button" aria-current={activeTab === tab.id ? 'page' : undefined}>
                <Icon name={tab.icon} />
                {tab.label}
                {tab.id === 'queue' && queueCount > 0 && <span className="bento-badge">{queueCount}</span>}
              </button>
            ))}
          </nav>
          <div className="studio-status">
            <span className="bento-status-dot" style={display?.is_mock ? { background: '#bd8b31' } : undefined} aria-hidden="true" />
            <span>{display?.is_mock ? 'Aperçu local' : 'Cadre Inky'}</span>
            {authRequired && (
              <button type="button" onClick={onLogout} className="bento-button bento-button-quiet studio-logout" title="Se déconnecter" aria-label="Se déconnecter">
                <Icon name="logout" size={18} />
              </button>
            )}
          </div>
        </div>
      </header>
      <main id="main-content" className="studio-main" tabIndex={-1}>
        {children}
        <footer className="studio-footer">
          <span>Inky Studio · Un peu de vie dans votre cadre.</span>
          {health && <span>Version {health.version}</span>}
        </footer>
      </main>
    </div>
  )
}
