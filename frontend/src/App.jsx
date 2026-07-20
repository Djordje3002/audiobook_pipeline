import { useCallback, useEffect, useMemo, useState } from 'react';

const SUPPORT_EMAIL = import.meta.env.VITE_SUPPORT_EMAIL || '';

const FALLBACK_LANGUAGES = [
  { code: 'en', name: 'English', native_name: 'English' },
  { code: 'de', name: 'German', native_name: 'Deutsch' },
  { code: 'es', name: 'Spanish', native_name: 'Español' },
  { code: 'fr', name: 'French', native_name: 'Français' },
  { code: 'it', name: 'Italian', native_name: 'Italiano' },
  { code: 'pt', name: 'Portuguese', native_name: 'Português' },
];

function Icon({ name, size = 20 }) {
  const paths = {
    arrow: <><path d="M5 12h14"/><path d="m13 6 6 6-6 6"/></>,
    back: <><path d="M19 12H5"/><path d="m11 18-6-6 6-6"/></>,
    check: <path d="m5 12 4 4L19 6"/>,
    chevron: <path d="m9 18 6-6-6-6"/>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    close: <><path d="m6 6 12 12"/><path d="m18 6-12 12"/></>,
    credits: <><path d="M12 3 3 8l9 5 9-5-9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/></>,
    download: <><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></>,
    file: <><path d="M6 2h8l4 4v16H6z"/><path d="M14 2v5h5"/><path d="M9 13h6M9 17h6"/></>,
    globe: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    logout: <><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M14 3h7v18h-7"/></>,
    plus: <><path d="M12 5v14"/><path d="M5 12h14"/></>,
    play: <path d="m8 5 11 7-11 7V5Z"/>,
    receipt: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2V3Z"/><path d="M9 8h6M9 12h6"/></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></>,
    spark: <><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 16 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z"/></>,
    upload: <><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v5h16v-5"/></>,
    wave: <><path d="M3 12h2l2-6 3 12 3-14 3 16 2-8h3"/></>,
  };
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {paths[name] || paths.spark}
    </svg>
  );
}

function Logo({ compact = false }) {
  return (
    <span className="brand" aria-label="AI Voice Translator">
      <span className="brand-mark"><span/><span/><span/><span/><span/></span>
      {!compact && <span className="brand-name">AI Voice<span> Translator</span></span>}
    </span>
  );
}

async function parseResponse(response) {
  const text = await response.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { error: text || 'Unexpected server response.' }; }
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

function formatDate(value) {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(new Date(value));
}

function formatDuration(seconds) {
  if (!seconds) return 'Analyzing source';
  const minutes = Math.ceil(Number(seconds) / 60);
  return `${minutes} min`;
}

function statusTone(status) {
  if (['success', 'ready', 'active'].includes(status)) return 'positive';
  if (['error', 'expired'].includes(status)) return 'negative';
  if (['running', 'queued', 'processing'].includes(status)) return 'working';
  return 'neutral';
}

function AppLink({ to, navigate, children, className = '' }) {
  return <a href={to} className={className} onClick={(event) => { event.preventDefault(); navigate(to); }}>{children}</a>;
}

function PublicNav({ session, navigate }) {
  return (
    <header className="public-nav">
      <AppLink to="/" navigate={navigate} className="logo-link"><Logo /></AppLink>
      <nav className="public-links" aria-label="Main navigation">
        <a href="#workflow">How it works</a>
        <a href="#languages">Languages</a>
        <a href="#pricing">Pricing</a>
      </nav>
      <div className="nav-actions">
        {session?.user ? (
          <button className="button button-dark" onClick={() => navigate('/app')}>Open studio <Icon name="arrow" size={17}/></button>
        ) : (
          <>
            <button className="button button-ghost" onClick={() => navigate('/login')}>Log in</button>
            <button className="button button-dark" onClick={() => navigate('/register')}>Start free <Icon name="arrow" size={17}/></button>
          </>
        )}
      </div>
    </header>
  );
}

function Waveform({ small = false }) {
  const bars = [28, 48, 34, 72, 52, 88, 42, 64, 92, 58, 38, 76, 48, 86, 32, 62, 44, 70, 36, 54, 30];
  return <div className={`waveform ${small ? 'waveform-small' : ''}`}>{bars.map((height, index) => <span key={index} style={{ '--bar': `${height}%`, '--delay': `${index * 35}ms` }}/>)}</div>;
}

function Landing({ session, navigate, languages }) {
  const featured = languages.slice(0, 12);
  return (
    <div className="marketing-page">
      <PublicNav session={session} navigate={navigate}/>
      <main>
        <section className="hero-section">
          <div className="hero-copy">
            <div className="announcement"><span>New</span> 34-language localization studio <Icon name="arrow" size={15}/></div>
            <h1>Your story,<br/><em>heard everywhere.</em></h1>
            <p className="hero-lede">Transform long-form audio into carefully translated, production-ready editions—without losing the voice, rhythm, or soul of the original.</p>
            <div className="hero-actions">
              <button className="button button-acid button-large" onClick={() => navigate(session?.user ? '/app/projects/new' : '/register')}>Localize your first chapter <Icon name="arrow"/></button>
              <a href="#workflow" className="text-link">See how it works <span>↓</span></a>
            </div>
            <div className="hero-proof">
              <div className="avatar-stack"><span>AM</span><span>JK</span><span>LN</span><span>+2k</span></div>
              <div><strong>Built for storytellers</strong><small>Audiobooks, podcasts & documentary</small></div>
            </div>
          </div>
          <div className="hero-visual" aria-label="Audio localization preview">
            <div className="orb orb-one"/><div className="orb orb-two"/>
            <div className="studio-window">
              <div className="studio-window-head"><span className="window-dots"><i/><i/><i/></span><span>Midnight Train · Chapter 01</span><span className="live-pill">AI studio</span></div>
              <div className="studio-track">
                <div className="track-meta"><span className="play-control"><Icon name="play" size={17}/></span><div><strong>Original narration</strong><small>Serbian · 04:32</small></div><span>00:48</span></div>
                <Waveform/>
              </div>
              <div className="translation-flow">
                <div className="language-node"><span>SR</span><div><strong>Serbian</strong><small>Source detected</small></div><Icon name="check" size={16}/></div>
                <div className="flow-line"><span/><Icon name="spark" size={18}/><span/></div>
                <div className="target-stack">
                  <div><b>EN</b><span>English</span><i>Ready</i></div>
                  <div><b>DE</b><span>German</span><i>Ready</i></div>
                  <div><b>ES</b><span>Spanish</span><i>Review</i></div>
                </div>
              </div>
              <div className="studio-caption"><Icon name="spark" size={17}/><span>Character names, terminology and narrative tone stay consistent across every edition.</span></div>
            </div>
            <div className="floating-card floating-top"><span className="success-orb"><Icon name="check" size={15}/></span><div><strong>Translation complete</strong><small>3 editions · 14m 08s</small></div></div>
            <div className="floating-card floating-bottom"><Icon name="globe"/><div><strong>34 languages</strong><small>One creative workspace</small></div></div>
          </div>
        </section>

        <section className="metric-strip">
          <p>Made for long-form audio where <strong>every word matters.</strong></p>
          <div><span><strong>34</strong> languages</span><span><strong>12×</strong> faster workflow</span><span><strong>1</strong> consistent glossary</span></div>
        </section>

        <section className="feature-section section-pad">
          <div className="section-kicker">More than translation</div>
          <div className="section-title-row"><h2>A complete localization desk,<br/>built around your story.</h2><p>Go from raw narration to an editable multilingual package in one focused workspace.</p></div>
          <div className="feature-grid">
            <article className="feature-card feature-dark"><span className="feature-icon"><Icon name="wave"/></span><div className="mini-wave"><Waveform small/></div><h3>Long-form aware</h3><p>Timestamped transcription, smart segmentation and resumable processing for full books—not just clips.</p><span className="feature-number">01</span></article>
            <article className="feature-card feature-lilac"><span className="feature-icon"><Icon name="spark"/></span><div className="glossary-demo"><span>Character</span><strong>Miloš</strong><span>Keep as</span><strong>Miloš</strong><i><Icon name="check" size={15}/></i></div><h3>Story memory</h3><p>A shared glossary protects character names, recurring phrases and the author’s stylistic choices.</p><span className="feature-number">02</span></article>
            <article className="feature-card feature-paper"><span className="feature-icon"><Icon name="grid"/></span><div className="edition-demo"><span>EN<small>English</small></span><span>DE<small>German</small></span><span>FR<small>French</small></span><b>+9</b></div><h3>One-to-many editions</h3><p>Transcribe once, then fan out to every target language with clean, isolated deliverables.</p><span className="feature-number">03</span></article>
          </div>
        </section>

        <section className="workflow-section section-pad" id="workflow">
          <div className="section-kicker light">The workflow</div>
          <h2>From one voice to a world of listeners.</h2>
          <div className="workflow-grid">
            {[
              ['01', 'Bring your story', 'Upload an audiobook, podcast episode, interview or documentary track.', 'upload'],
              ['02', 'Choose your listeners', 'Select one or many target languages and confirm your rights.', 'globe'],
              ['03', 'Shape every edition', 'Review transcript, terminology, warnings and translated deliverables.', 'spark'],
              ['04', 'Publish with confidence', 'Download structured assets today; synthetic voice production is ready to connect.', 'download'],
            ].map(([number, title, copy, icon]) => <article key={number}><span>{number}</span><i><Icon name={icon}/></i><h3>{title}</h3><p>{copy}</p></article>)}
          </div>
        </section>

        <section className="languages-section section-pad" id="languages">
          <div className="languages-copy"><div className="section-kicker">Speak human, globally</div><h2>Local nuance.<br/><em>Global reach.</em></h2><p>Start with automatic source detection or choose the language yourself. Every edition gets its own clean artifact trail.</p><button className="button button-dark" onClick={() => navigate(session?.user ? '/app/projects/new' : '/register')}>Explore the studio <Icon name="arrow"/></button></div>
          <div className="language-cloud">
            {featured.map((language, index) => <div key={language.code} className={index % 4 === 0 ? 'language-chip featured' : 'language-chip'}><span>{language.code.toUpperCase()}</span><strong>{language.native_name}</strong><small>{language.name}</small></div>)}
            <div className="language-chip more"><strong>+{Math.max(0, languages.length - featured.length)}</strong><small>more languages</small></div>
          </div>
        </section>

        <section className="trust-section">
          <div><span className="trust-lock"><Icon name="check"/></span><div className="section-kicker light">Rights-first AI</div><h2>Creative power should come with clear consent.</h2><p>Every production workspace records content rights and narrator consent before processing. Your files stay scoped to your organization and synthetic output remains traceable.</p></div>
          <ul><li><Icon name="check"/>Explicit rights confirmation</li><li><Icon name="check"/>Narrator consent audit trail</li><li><Icon name="check"/>Private organization workspaces</li><li><Icon name="check"/>Secure object storage ready</li></ul>
        </section>

        <section className="pricing-section section-pad" id="pricing">
          <div className="section-kicker">Simple credits, serious output</div><h2>Pay for localized minutes.<br/>Nothing mysterious.</h2>
          <div className="pricing-grid">
            <article><span className="plan-label">Free</span><h3>$0<small>/forever</small></h3><p>Test a real chapter before committing.</p><strong>15 localized minutes</strong><ul><li><Icon name="check"/>All languages</li><li><Icon name="check"/>Translation artifacts</li><li><Icon name="check"/>One private studio</li></ul><button className="button button-outline" onClick={() => navigate('/register')}>Start free</button></article>
            <article className="plan-featured"><span className="popular">Most popular</span><span className="plan-label">Creator</span><h3>$29<small>/month</small></h3><p>For authors and independent producers.</p><strong>300 localized minutes / month</strong><ul><li><Icon name="check"/>Multiple target editions</li><li><Icon name="check"/>Glossary consistency</li><li><Icon name="check"/>Priority processing</li></ul><button className="button button-acid" onClick={() => navigate(session?.user ? '/app/billing' : '/register')}>Choose Creator</button></article>
            <article><span className="plan-label">Studio</span><h3>$79<small>/month</small></h3><p>For teams shipping a global catalog.</p><strong>1,200 localized minutes / month</strong><ul><li><Icon name="check"/>Shared organization</li><li><Icon name="check"/>Larger production volume</li><li><Icon name="check"/>Billing portal access</li></ul><button className="button button-outline" onClick={() => navigate(session?.user ? '/app/billing' : '/register')}>Choose Studio</button></article>
          </div>
          <p className="billing-note">Payments, taxes and invoices are handled securely by Lemon Squeezy, our Merchant of Record.</p>
        </section>

        <section className="final-cta"><Logo compact/><h2>One story.<br/><em>Every language.</em></h2><p>Your first 15 localized minutes are on us.</p><button className="button button-acid button-large" onClick={() => navigate(session?.user ? '/app/projects/new' : '/register')}>Open your studio <Icon name="arrow"/></button></section>
      </main>
      <footer className="public-footer"><Logo/><p>Thoughtful AI localization for the world’s stories.</p><div>{SUPPORT_EMAIL && <a href={`mailto:${SUPPORT_EMAIL}`}>Contact</a>}<span>© 2026 AI Voice Translator</span></div></footer>
    </div>
  );
}

function AuthPage({ mode, navigate, onAuthenticated }) {
  const isRegister = mode === 'register';
  const [form, setForm] = useState({ display_name: '', email: '', password: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await fetch(`/api/auth/${mode}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      const data = await parseResponse(response);
      onAuthenticated(data); navigate('/app');
    } catch (requestError) { setError(requestError.message); } finally { setBusy(false); }
  }
  return (
    <div className="auth-page">
      <div className="auth-brand-panel">
        <AppLink to="/" navigate={navigate}><Logo/></AppLink>
        <div><span className="section-kicker light">Your private studio</span><h1>One voice can<br/><em>travel the world.</em></h1><p>Build faithful multilingual editions from one long-form source.</p></div>
        <div className="auth-wave"><Waveform/><span>34 languages · one story memory</span></div>
      </div>
      <div className="auth-form-panel">
        <div className="auth-mobile-logo"><AppLink to="/" navigate={navigate}><Logo/></AppLink></div>
        <form className="auth-form" onSubmit={submit}>
          <span className="auth-step">{isRegister ? 'START FREE' : 'WELCOME BACK'}</span>
          <h2>{isRegister ? 'Create your studio.' : 'Return to your stories.'}</h2>
          <p>{isRegister ? '15 localized minutes included. No card required.' : 'Enter your account details to continue.'}</p>
          {isRegister && <label><span>Your name</span><input autoFocus required minLength="2" maxLength="120" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} placeholder="Ana Marković"/></label>}
          <label><span>Email address</span><input autoFocus={!isRegister} required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="you@studio.com"/></label>
          <label><span>Password</span><input required type="password" minLength="10" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="At least 10 characters"/></label>
          {error && <div className="form-error">{error}</div>}
          <button className="button button-dark button-full" disabled={busy}>{busy ? 'Please wait…' : isRegister ? 'Create free studio' : 'Log in'} <Icon name="arrow"/></button>
          <div className="auth-switch">{isRegister ? 'Already have an account?' : 'New here?'} <button type="button" onClick={() => navigate(isRegister ? '/login' : '/register')}>{isRegister ? 'Log in' : 'Start free'}</button></div>
          <small className="terms">By continuing, you agree to responsible use of AI-generated media and confirm you will only process content you have rights to use.</small>
        </form>
      </div>
    </div>
  );
}

function AppShell({ session, navigate, active, onLogout, children, credits }) {
  const user = session.user;
  const initials = user.display_name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase();
  const items = [['dashboard', '/app', 'grid', 'Overview'], ['projects', '/app/projects/new', 'plus', 'New project'], ['billing', '/app/billing', 'receipt', 'Plans & credits']];
  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <AppLink to="/" navigate={navigate} className="sidebar-logo"><Logo/></AppLink>
        <nav>{items.map(([key, to, icon, label]) => <AppLink key={key} to={to} navigate={navigate} className={active === key ? 'active' : ''}><Icon name={icon}/><span>{label}</span></AppLink>)}</nav>
        <div className="sidebar-bottom">
          <div className="mini-credit"><Icon name="credits"/><div><small>Available</small><strong>{credits ?? '—'} credits</strong></div></div>
          <button onClick={onLogout}><span className="user-avatar">{initials}</span><span><strong>{user.display_name}</strong><small>{user.email}</small></span><Icon name="logout" size={18}/></button>
        </div>
      </aside>
      <div className="app-main">{children}</div>
    </div>
  );
}

function AppHeader({ eyebrow, title, copy, action }) {
  return <header className="app-header"><div><span>{eyebrow}</span><h1>{title}</h1>{copy && <p>{copy}</p>}</div>{action}</header>;
}

function EmptyProjects({ navigate }) {
  return <div className="empty-state"><div className="empty-visual"><span><Icon name="wave" size={30}/></span><Waveform small/></div><h3>Your first global edition starts here.</h3><p>Upload a chapter, select listeners around the world, and let the studio build the first draft.</p><button className="button button-dark" onClick={() => navigate('/app/projects/new')}><Icon name="plus"/> Create first project</button></div>;
}

function Dashboard({ session, request, navigate, credits, refreshBilling }) {
  const [projects, setProjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => { request('/api/projects').then((data) => setProjects(data.projects || [])).catch((err) => setError(err.message)).finally(() => setLoading(false)); refreshBilling(); }, [request, refreshBilling]);
  const ready = projects.filter((project) => project.status === 'ready').length;
  const languageCount = new Set(projects.flatMap((project) => project.target_languages)).size;
  return (
    <div className="dashboard-page page-content">
      <AppHeader eyebrow="YOUR STUDIO" title={`Good ${new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}, ${session.user.display_name.split(' ')[0]}.`} copy="Your stories are ready to travel." action={<button className="button button-dark" onClick={() => navigate('/app/projects/new')}><Icon name="plus"/> New project</button>}/>
      <section className="stats-row"><article><span><Icon name="file"/></span><div><small>Total projects</small><strong>{projects.length}</strong></div></article><article><span><Icon name="check"/></span><div><small>Ready sources</small><strong>{ready}</strong></div></article><article><span><Icon name="globe"/></span><div><small>Target languages</small><strong>{languageCount}</strong></div></article><article className="credit-stat"><span><Icon name="credits"/></span><div><small>Localized minutes</small><strong>{credits ?? '—'}</strong></div><button onClick={() => navigate('/app/billing')}>Add more</button></article></section>
      <section className="dashboard-section"><div className="section-head"><div><h2>Recent projects</h2><p>Every story and edition in one place.</p></div>{projects.length > 0 && <button className="text-button" onClick={() => navigate('/app/projects/new')}>New project <Icon name="arrow" size={16}/></button>}</div>
        {error && <div className="form-error">{error}</div>}
        {loading ? <div className="loading-block"><span/><span/><span/></div> : projects.length === 0 ? <EmptyProjects navigate={navigate}/> : <div className="project-grid">{projects.map((project) => <button className="project-card" key={project.id} onClick={() => navigate(`/app/projects/${project.id}`)}><div className="project-card-top"><span className="project-icon"><Icon name="wave"/></span><span className={`status-pill ${statusTone(project.status)}`}>{project.status}</span></div><h3>{project.title}</h3><div className="language-route"><b>{project.source_language.toUpperCase()}</b><span/><div>{project.target_languages.slice(0, 3).map((code) => <i key={code}>{code.toUpperCase()}</i>)}{project.target_languages.length > 3 && <i>+{project.target_languages.length - 3}</i>}</div></div><footer><span><Icon name="clock" size={15}/>{formatDuration(project.duration_seconds)}</span><span>{formatDate(project.updated_at)}</span><Icon name="chevron" size={17}/></footer></button>)}</div>}
      </section>
      <section className="dashboard-callout"><div><span className="section-kicker light">A better first pass</span><h2>Localize the meaning,<br/>not just the words.</h2><p>Your studio keeps an evolving story glossary beside every edition.</p></div><div className="callout-quote"><span>“</span><p>The city never slept; it only changed its alibi.</p><small>Original tone preserved across 3 editions</small></div></section>
    </div>
  );
}

function LanguagePicker({ languages, sourceLanguage, selected, setSelected }) {
  const [query, setQuery] = useState('');
  const filtered = languages.filter((language) => language.code !== sourceLanguage && `${language.name} ${language.native_name} ${language.code}`.toLowerCase().includes(query.toLowerCase()));
  function toggle(code) { setSelected(selected.includes(code) ? selected.filter((item) => item !== code) : selected.length < 12 ? [...selected, code] : selected); }
  return <div className="language-picker"><div className="picker-search"><Icon name="search" size={18}/><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search languages"/><span>{selected.length}/12</span></div><div className="language-options">{filtered.map((language) => <button type="button" key={language.code} className={selected.includes(language.code) ? 'selected' : ''} onClick={() => toggle(language.code)}><b>{language.code.toUpperCase()}</b><span><strong>{language.name}</strong><small>{language.native_name}</small></span>{selected.includes(language.code) && <i><Icon name="check" size={15}/></i>}</button>)}</div></div>;
}

function NewProject({ session, languages, request, navigate, refreshBilling }) {
  const [step, setStep] = useState(1);
  const [title, setTitle] = useState('');
  const [sourceLanguage, setSourceLanguage] = useState('auto');
  const [targets, setTargets] = useState(['en']);
  const [file, setFile] = useState(null);
  const [rights, setRights] = useState(false);
  const [consent, setConsent] = useState(false);
  const [speaker, setSpeaker] = useState('Primary narrator');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const organization = session.organizations[0];
  const sourceOptions = [{ code: 'auto', name: 'Automatic detection', native_name: 'Recommended' }, ...languages];
  async function createProject() {
    setBusy(true); setError('');
    try {
      const created = await request('/api/projects', { method: 'POST', body: { organization_id: organization.id, title, source_language: sourceLanguage, target_languages: targets, rights_confirmed: rights, voice_consent_confirmed: consent, speaker_name: speaker } });
      const form = new FormData(); form.append('file', file);
      await request(`/api/projects/${created.project.id}/source`, { method: 'POST', body: form });
      refreshBilling(); navigate(`/app/projects/${created.project.id}`);
    } catch (requestError) { setError(requestError.message); setBusy(false); }
  }
  const canContinue = step === 1 ? title.trim().length >= 2 && file : step === 2 ? targets.length > 0 && !(sourceLanguage !== 'auto' && targets.includes(sourceLanguage)) : rights && consent && speaker.trim();
  return (
    <div className="wizard-page page-content">
      <button className="back-link" onClick={() => navigate('/app')}><Icon name="back" size={17}/> Back to studio</button>
      <div className="wizard-layout">
        <aside className="wizard-side"><span className="section-kicker light">NEW LOCALIZATION</span><h1>Take your story<br/><em>somewhere new.</em></h1><p>We’ll build one source transcript and a separate edition for every listener group you choose.</p><div className="wizard-progress">{[['Story & source', 1], ['Audience', 2], ['Rights & consent', 3]].map(([label, number]) => <div key={number} className={step === number ? 'active' : step > number ? 'done' : ''}><span>{step > number ? <Icon name="check" size={15}/> : number}</span><strong>{label}</strong></div>)}</div><div className="wizard-tip"><Icon name="spark"/><span><strong>Credit math</strong>1 credit = 1 source minute × 1 target language.</span></div></aside>
        <section className="wizard-card">
          {step === 1 && <><span className="form-step">STEP 1 OF 3</span><h2>What are we localizing?</h2><p>Give the project a clear name and bring the original recording.</p><label className="field"><span>Project title</span><input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. The Midnight Train" maxLength="240"/></label><label className="field"><span>Source language</span><select value={sourceLanguage} onChange={(e) => setSourceLanguage(e.target.value)}>{sourceOptions.map((language) => <option key={language.code} value={language.code}>{language.name} — {language.native_name}</option>)}</select></label><label className={`upload-zone ${file ? 'has-file' : ''}`}><input type="file" accept="audio/*,video/*,.mp3,.wav,.m4a,.flac,.aac,.ogg,.mp4,.mov,.mkv" onChange={(e) => setFile(e.target.files?.[0] || null)}/>{file ? <><span className="upload-icon"><Icon name="file"/></span><div><strong>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(1)} MB · ready to upload</small></div><i><Icon name="check"/></i></> : <><span className="upload-icon"><Icon name="upload"/></span><div><strong>Drop your recording here</strong><small>MP3, WAV, M4A, FLAC, AAC or video · up to 2 GB</small></div><b>Browse file</b></>}</label></>}
          {step === 2 && <><span className="form-step">STEP 2 OF 3</span><h2>Who should hear it?</h2><p>Select up to 12 target languages. Each one becomes its own editable edition.</p><LanguagePicker languages={languages} sourceLanguage={sourceLanguage} selected={targets} setSelected={setTargets}/>{sourceLanguage !== 'auto' && targets.includes(sourceLanguage) && <div className="form-error">Source and target languages must be different.</div>}</>}
          {step === 3 && <><span className="form-step">STEP 3 OF 3</span><h2>Protect the people behind the story.</h2><p>These confirmations create an auditable record for responsible localization and future synthetic voice work.</p><label className="field"><span>Narrator / rights holder</span><input value={speaker} onChange={(e) => setSpeaker(e.target.value)} placeholder="Full name or role"/></label><label className={`consent-card ${rights ? 'checked' : ''}`}><input type="checkbox" checked={rights} onChange={(e) => setRights(e.target.checked)}/><span><Icon name="check" size={15}/></span><div><strong>I have the necessary content rights.</strong><small>I own this work or have permission to transcribe, translate and create localized editions.</small></div></label><label className={`consent-card ${consent ? 'checked' : ''}`}><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}/><span><Icon name="check" size={15}/></span><div><strong>The narrator has consented.</strong><small>The speaker has authorized this use of their performance and any future synthetic voice processing.</small></div></label><div className="summary-card"><div><small>Project</small><strong>{title}</strong></div><div><small>Route</small><strong>{sourceLanguage.toUpperCase()} → {targets.map((code) => code.toUpperCase()).join(', ')}</strong></div><div><small>File</small><strong>{file?.name}</strong></div></div></>}
          {error && <div className="form-error">{error}</div>}
          <footer className="wizard-actions">{step > 1 ? <button className="button button-ghost" onClick={() => setStep(step - 1)} disabled={busy}><Icon name="back" size={17}/> Back</button> : <span/>}<button className="button button-dark" disabled={!canContinue || busy} onClick={() => step < 3 ? setStep(step + 1) : createProject()}>{busy ? 'Creating studio…' : step < 3 ? 'Continue' : 'Create project'} {!busy && <Icon name="arrow" size={18}/>}</button></footer>
        </section>
      </div>
    </div>
  );
}

function ProjectStudio({ projectId, request, navigate, refreshBilling }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');
  const [busyMode, setBusyMode] = useState('');
  const [tab, setTab] = useState('overview');
  const load = useCallback(() => request(`/api/projects/${projectId}`).then(setDetail).catch((err) => setError(err.message)), [projectId, request]);
  useEffect(() => { load(); }, [load]);
  const latestJob = detail?.jobs?.[0];
  useEffect(() => { if (!latestJob || !['queued', 'running', 'retrying'].includes(latestJob.status)) return undefined; const timer = setInterval(load, 2500); return () => clearInterval(timer); }, [latestJob?.id, latestJob?.status, load]);
  async function startJob(mode) { setBusyMode(mode); setError(''); try { await request(`/api/projects/${projectId}/jobs`, { method: 'POST', headers: { 'Idempotency-Key': `${projectId}-${mode}-${Date.now()}` }, body: { mode } }); await load(); refreshBilling(); } catch (requestError) { setError(requestError.message); } finally { setBusyMode(''); } }
  if (!detail) return <div className="page-content"><div className="loading-block tall"><span/><span/><span/></div>{error && <div className="form-error">{error}</div>}</div>;
  const { project, artifacts = [], jobs = [] } = detail;
  const resultArtifacts = artifacts.filter((artifact) => artifact.kind !== 'source');
  return (
    <div className="studio-page page-content">
      <button className="back-link" onClick={() => navigate('/app')}><Icon name="back" size={17}/> All projects</button>
      <header className="studio-header"><div className="studio-title-icon"><Icon name="wave" size={28}/></div><div><div className="studio-title-line"><h1>{project.title}</h1><span className={`status-pill ${statusTone(project.status)}`}>{project.status}</span></div><p><span>{project.source_language.toUpperCase()}</span><b>→</b>{project.target_languages.map((code) => <i key={code}>{code.toUpperCase()}</i>)} · {formatDuration(project.duration_seconds)}</p></div><button className="button button-dark" disabled={busyMode || ['queued', 'running'].includes(latestJob?.status)} onClick={() => startJob('preview')}><Icon name="play" size={17}/>{busyMode === 'preview' ? 'Starting…' : 'Run preview'}</button></header>
      {error && <div className="form-error studio-error">{error}</div>}
      <nav className="studio-tabs">{[['overview', 'Overview'], ['outputs', `Outputs (${resultArtifacts.length})`], ['activity', `Activity (${jobs.length})`]].map(([key, label]) => <button className={tab === key ? 'active' : ''} key={key} onClick={() => setTab(key)}>{label}</button>)}</nav>
      {tab === 'overview' && <div className="studio-overview-grid"><section className="studio-panel source-panel"><div className="panel-head"><div><span className="section-kicker">SOURCE</span><h2>Original recording</h2></div><span className="source-ready"><Icon name="check" size={15}/> secured</span></div>{artifacts.filter((a) => a.kind === 'source').map((artifact) => <div className="source-file" key={artifact.id}><span><Icon name="file"/></span><div><strong>{artifact.original_filename}</strong><small>{(artifact.size_bytes / 1024 / 1024).toFixed(1)} MB · {project.source_language === 'auto' ? 'auto-detect language' : project.source_language.toUpperCase()}</small></div></div>)}<Waveform/><div className="consent-summary"><span><Icon name="check" size={15}/></span><div><strong>Rights and narrator consent recorded</strong><small>This project is cleared for its configured localization workflow.</small></div></div></section><section className="studio-panel production-panel"><div className="panel-head"><div><span className="section-kicker">PRODUCTION</span><h2>Create localized editions</h2></div></div><div className="production-options"><button disabled={busyMode || ['queued', 'running'].includes(latestJob?.status)} onClick={() => startJob('preview')}><span><Icon name="play"/></span><div><strong>Chapter preview</strong><small>First {Math.min(5, Math.ceil((project.duration_seconds || 300) / 60))} minutes × {project.target_languages.length} languages</small></div><Icon name="chevron"/></button><button disabled={busyMode || ['queued', 'running'].includes(latestJob?.status)} onClick={() => startJob('full')}><span><Icon name="spark"/></span><div><strong>Full translation</strong><small>{formatDuration(project.duration_seconds)} × {project.target_languages.length} target editions</small></div><Icon name="chevron"/></button></div><p className="production-note"><Icon name="credits" size={16}/> Credits are reserved when a job starts and returned automatically if it fails.</p></section>{latestJob && <section className="studio-panel current-job"><div className="panel-head"><div><span className="section-kicker">LATEST JOB</span><h2>{latestJob.mode === 'preview' ? 'Chapter preview' : 'Full translation'}</h2></div><span className={`status-pill ${statusTone(latestJob.status)}`}>{latestJob.status}</span></div><div className="job-progress"><div><span>{latestJob.stage}</span><strong>{latestJob.progress_percent}%</strong></div><span><i style={{ width: `${latestJob.progress_percent}%` }}/></span></div>{latestJob.error && <div className="form-error">{latestJob.error}</div>}<div className="job-meta"><span>Created {formatDate(latestJob.created_at)}</span><span>{latestJob.finished_at ? `Finished ${formatDate(latestJob.finished_at)}` : 'Safe to leave this page'}</span></div></section>}<section className="studio-panel edition-panel"><div className="panel-head"><div><span className="section-kicker">EDITIONS</span><h2>Target package</h2></div><button className="text-button" onClick={() => setTab('outputs')}>View outputs <Icon name="arrow" size={15}/></button></div><div className="edition-list">{project.target_languages.map((code) => { const outputs = resultArtifacts.filter((a) => a.language === code); return <div key={code}><b>{code.toUpperCase()}</b><span><strong>{code}</strong><small>{outputs.length ? `${outputs.length} assets ready` : 'Waiting for production'}</small></span>{outputs.length ? <i className="ready"><Icon name="check" size={14}/></i> : <i/>}</div>; })}</div></section></div>}
      {tab === 'outputs' && <section className="outputs-panel"><div className="section-head"><div><h2>Production outputs</h2><p>Download timestamped transcripts, glossaries and translated editions.</p></div></div>{resultArtifacts.length === 0 ? <div className="empty-state compact"><span className="empty-visual"><Icon name="download" size={28}/></span><h3>No outputs yet.</h3><p>Run a chapter preview to create the first multilingual package.</p></div> : <div className="artifact-table"><div className="artifact-row artifact-head"><span>Asset</span><span>Language</span><span>Size</span><span>Created</span><span/></div>{resultArtifacts.map((artifact) => <div className="artifact-row" key={artifact.id}><span><i><Icon name="file" size={18}/></i><strong>{artifact.kind}</strong><small>{artifact.original_filename}</small></span><span><b>{(artifact.language || '—').toUpperCase()}</b></span><span>{Math.max(1, Math.round(artifact.size_bytes / 1024))} KB</span><span>{formatDate(artifact.created_at)}</span><a href={`/api/projects/${project.id}/artifacts/${artifact.id}/download`}><Icon name="download" size={17}/> Download</a></div>)}</div>}</section>}
      {tab === 'activity' && <section className="activity-panel"><div className="section-head"><div><h2>Project activity</h2><p>A traceable history of production attempts.</p></div></div>{jobs.length === 0 ? <div className="empty-state compact"><h3>No jobs started yet.</h3></div> : <div className="activity-list">{jobs.map((job) => <div key={job.id}><span className={`activity-dot ${statusTone(job.status)}`}/><div><strong>{job.mode === 'preview' ? 'Chapter preview' : 'Full translation'}</strong><small>{job.stage} · {job.progress_percent}%</small></div><span className={`status-pill ${statusTone(job.status)}`}>{job.status}</span><time>{formatDate(job.created_at)}</time></div>)}</div>}</section>}
    </div>
  );
}

function Billing({ session, request, navigate, billing, refreshBilling }) {
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const organization = session.organizations[0];
  useEffect(() => { refreshBilling(); }, [refreshBilling]);
  async function checkout(planKey) { setBusy(planKey); setError(''); try { const data = await request('/api/billing/checkout', { method: 'POST', body: { organization_id: organization.id, plan_key: planKey } }); window.location.assign(data.checkout_url); } catch (err) { setError(err.message); setBusy(''); } }
  async function portal() { setBusy('portal'); setError(''); try { const data = await request('/api/billing/portal', { method: 'POST', body: { organization_id: organization.id } }); window.location.assign(data.portal_url); } catch (err) { setError(err.message); setBusy(''); } }
  return <div className="billing-page page-content"><AppHeader eyebrow="PLANS & CREDITS" title="Grow your global catalog." copy="One credit covers one source minute in one target language." action={<button className="button button-ghost" onClick={() => navigate('/app')}><Icon name="back" size={17}/> Overview</button>}/>{error && <div className="form-error studio-error">{error}</div>}<section className="billing-balance"><div><span><Icon name="credits" size={26}/></span><div><small>Available balance</small><strong>{billing?.credit_balance ?? '—'} <i>localized minutes</i></strong></div></div>{billing?.subscription ? <div><span className="status-pill positive">{billing.subscription.status}</span><strong>{billing.subscription.plan_key} plan</strong><button className="text-button" disabled={busy} onClick={portal}>Manage billing <Icon name="arrow" size={15}/></button></div> : <div><span className="status-pill neutral">free</span><strong>Starter studio</strong><small>No card on file</small></div>}</section><div className="billing-plan-grid"><article><span className="plan-label">Creator</span><h2>$29<small>/month</small></h2><p>For authors, podcasters and solo producers shipping consistently.</p><strong>300 localized minutes</strong><ul><li><Icon name="check"/>All 34 languages</li><li><Icon name="check"/>One-to-many processing</li><li><Icon name="check"/>Private artifacts</li><li><Icon name="check"/>Story glossary</li></ul><button className="button button-dark button-full" disabled={busy || Boolean(billing?.subscription) || !billing?.checkout_configured} onClick={() => checkout('creator')}>{busy === 'creator' ? 'Opening checkout…' : billing?.subscription ? 'Current subscription active' : billing?.checkout_configured ? 'Choose Creator' : 'Checkout setup required'}</button></article><article className="studio-plan"><span className="popular">BEST VALUE</span><span className="plan-label">Studio</span><h2>$79<small>/month</small></h2><p>For production teams managing a multilingual publishing calendar.</p><strong>1,200 localized minutes</strong><ul><li><Icon name="check"/>Everything in Creator</li><li><Icon name="check"/>4× monthly volume</li><li><Icon name="check"/>Organization workspace</li><li><Icon name="check"/>Priority queue ready</li></ul><button className="button button-acid button-full" disabled={busy || Boolean(billing?.subscription) || !billing?.checkout_configured} onClick={() => checkout('studio')}>{busy === 'studio' ? 'Opening checkout…' : billing?.subscription ? 'Manage your current plan' : billing?.checkout_configured ? 'Choose Studio' : 'Checkout setup required'}</button></article></div><section className="billing-faq"><div><h3>How credits work</h3><p>A 10-minute chapter localized into English, German and Spanish uses 30 credits. Transcription is reused across languages.</p></div><div><h3>What if a job fails?</h3><p>Reserved credits return automatically. You only spend credits on a successfully delivered production job.</p></div><div><h3>Who handles payment?</h3><p>Lemon Squeezy acts as Merchant of Record and handles checkout, tax calculation, invoices and the customer portal.</p></div></section></div>;
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [languages, setLanguages] = useState(FALLBACK_LANGUAGES);
  const [billing, setBilling] = useState(null);

  const navigate = useCallback((to) => { window.history.pushState({}, '', to); setPath(to); window.scrollTo({ top: 0, behavior: 'smooth' }); }, []);
  useEffect(() => { const handler = () => setPath(window.location.pathname); window.addEventListener('popstate', handler); return () => window.removeEventListener('popstate', handler); }, []);
  useEffect(() => { Promise.all([fetch('/api/auth/me').then(parseResponse), fetch('/api/languages').then(parseResponse)]).then(([auth, languageData]) => { setSession(auth.user ? auth : null); if (languageData.languages?.length) setLanguages(languageData.languages); }).finally(() => setLoading(false)); }, []);

  const request = useCallback(async (url, options = {}) => {
    const headers = { ...(options.headers || {}) };
    let body = options.body;
    if (body && !(body instanceof FormData)) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(body); }
    if (session?.csrf_token && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = session.csrf_token;
    return parseResponse(await fetch(url, { ...options, headers, body }));
  }, [session?.csrf_token]);

  const refreshBilling = useCallback(async () => {
    const organizationId = session?.organizations?.[0]?.id;
    if (!organizationId) return;
    try { setBilling(await request(`/api/billing?organization_id=${organizationId}`)); } catch { setBilling(null); }
  }, [request, session?.organizations]);
  useEffect(() => { if (session) refreshBilling(); }, [session, refreshBilling]);

  async function logout() { try { await request('/api/auth/logout', { method: 'POST' }); } finally { setSession(null); setBilling(null); navigate('/'); } }
  if (loading) return <div className="app-loader"><Logo/><Waveform small/><span>Preparing your studio</span></div>;
  if (path === '/') return <Landing session={session} navigate={navigate} languages={languages}/>;
  if (path === '/login' || path === '/register') return session ? <DashboardRedirect navigate={navigate}/> : <AuthPage mode={path.slice(1)} navigate={navigate} onAuthenticated={setSession}/>;
  if (!session) return <AuthPage mode="login" navigate={navigate} onAuthenticated={setSession}/>;

  let active = 'dashboard'; let content;
  if (path === '/app/projects/new') { active = 'projects'; content = <NewProject session={session} languages={languages} request={request} navigate={navigate} refreshBilling={refreshBilling}/>; }
  else if (path === '/app/billing') { active = 'billing'; content = <Billing session={session} request={request} navigate={navigate} billing={billing} refreshBilling={refreshBilling}/>; }
  else if (/^\/app\/projects\/[^/]+$/.test(path)) { active = 'dashboard'; content = <ProjectStudio projectId={path.split('/').pop()} request={request} navigate={navigate} refreshBilling={refreshBilling}/>; }
  else content = <Dashboard session={session} request={request} navigate={navigate} credits={billing?.credit_balance} refreshBilling={refreshBilling}/>;
  return <AppShell session={session} navigate={navigate} active={active} onLogout={logout} credits={billing?.credit_balance}>{content}</AppShell>;
}

function DashboardRedirect({ navigate }) {
  useEffect(() => { navigate('/app'); }, [navigate]);
  return <div className="app-loader"><Logo/></div>;
}
