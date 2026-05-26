/**
 * Simple i18n module for Roundtable Web Viewer.
 * Supports zh-CN (default) and en-US.
 *
 * Usage:
 *   import { t, setLang, getLang } from './i18n.js';
 *   t('waiting')  // → "讨论即将开始…" or "Discussion starting…"
 */

const translations = {
  'zh-CN': {
    // Header
    'status.waiting': '等待中',
    'status.active': '讨论中',
    'status.concluded': '已结束',
    'share': '分享',
    'connected': '已连接',
    'reconnecting': '重连中…',
    'disconnected': '已断开',

    // Waiting state
    'waiting.title': '讨论即将开始…',
    'waiting.subtitle': '发言将会实时显示在这里',

    // Active state
    'participants.count': '位参与者',
    'participants.title': '参与者',
    'speeches.count': '条发言',

    // Round sections
    'round.opening': '📢 开场发言 (Round 0)',
    'round.discussion': '💬 第 {n} 轮讨论 (Round {n})',

    // Conclusion
    'conclusion.title': '📌 讨论结论',

    // Replay
    'replay.entry.title': '回放讨论全过程',
    'replay.back': '返回',
    'replay.title': '回放',

    // Share
    'share.title': '📋 分享链接',
    'share.hint': '任何人通过此链接可查看讨论',
    'share.copy': '复制',
    'share.copied': '已复制',
    'share.revoke': '⚠️ 撤销链接',
    'share.revoked': '链接已撤销',
    'share.mobile': '分享讨论',

    // Revoke modal
    'revoke.title': '确认撤销链接？',
    'revoke.desc': '撤销后，所有通过此链接的访问将在 5 秒内失效，且不可恢复。',
    'revoke.cancel': '取消',
    'revoke.confirm': '确认撤销',

    // Revoked state
    'revoked.icon': '🔒',
    'revoked.title': '此讨论链接已失效',
    'revoked.desc': '创作者已撤销了此链接的访问权限',
    'revoked.brand': 'Roundtable AI · 圆桌讨论',

    // Export
    'export.btn': '导出',
    'export.markdown': 'Markdown',
    'export.pdf': 'PDF',
    'export.title': '导出讨论结果',
    'export.downloading': '正在生成…',

    // Password
    'password.title': '🔒 访问验证',
    'password.desc': '此讨论需要密码才能查看',
    'password.placeholder': '请输入访问密码',
    'password.submit': '进入',
    'password.error': '密码错误，请重试',
    'password.required': '请输入密码',

    // Viewpoint cards
    'viewpoint.consensus': '✅ 共识',
    'viewpoint.disagreement': '❌ 分歧',
    'viewpoint.new_points': '💡 新观点',
    'viewpoint.convergence': '收敛度',

    // Scroll
    'scroll.new_messages': '↓ 新消息',

    // Page title
    'page.title': '圆桌讨论',

    // Language
    'lang.switch': 'EN',
    'lang.name': '中文',
  },

  'en-US': {
    // Header
    'status.waiting': 'Waiting',
    'status.active': 'Active',
    'status.concluded': 'Concluded',
    'share': 'Share',
    'connected': 'Connected',
    'reconnecting': 'Reconnecting…',
    'disconnected': 'Disconnected',

    // Waiting state
    'waiting.title': 'Discussion starting soon…',
    'waiting.subtitle': 'Speeches will appear here in real-time',

    // Active state
    'participants.count': 'participants',
    'participants.title': 'Participants',
    'speeches.count': 'speeches',

    // Round sections
    'round.opening': '📢 Opening (Round 0)',
    'round.discussion': '💬 Round {n} Discussion',

    // Conclusion
    'conclusion.title': '📌 Conclusion',

    // Replay
    'replay.entry.title': 'Replay Full Discussion',
    'replay.back': 'Back',
    'replay.title': 'Replay',

    // Share
    'share.title': '📋 Share Link',
    'share.hint': 'Anyone with this link can view the discussion',
    'share.copy': 'Copy',
    'share.copied': 'Copied!',
    'share.revoke': '⚠️ Revoke Link',
    'share.revoked': 'Link Revoked',
    'share.mobile': 'Share Discussion',

    // Revoke modal
    'revoke.title': 'Revoke Link?',
    'revoke.desc': 'Once revoked, all access via this link will be invalidated within 5 seconds and cannot be recovered.',
    'revoke.cancel': 'Cancel',
    'revoke.confirm': 'Revoke',

    // Revoked state
    'revoked.icon': '🔒',
    'revoked.title': 'This link has been revoked',
    'revoked.desc': 'The creator has revoked access to this link',
    'revoked.brand': 'Roundtable AI · Discussion',

    // Export
    'export.btn': 'Export',
    'export.markdown': 'Markdown',
    'export.pdf': 'PDF',
    'export.title': 'Export Discussion',
    'export.downloading': 'Generating…',

    // Password
    'password.title': '🔒 Access Verification',
    'password.desc': 'This discussion requires a password to view',
    'password.placeholder': 'Enter access password',
    'password.submit': 'Enter',
    'password.error': 'Incorrect password, please try again',
    'password.required': 'Please enter a password',

    // Viewpoint cards
    'viewpoint.consensus': '✅ Consensus',
    'viewpoint.disagreement': '❌ Disagreement',
    'viewpoint.new_points': '💡 New Points',
    'viewpoint.convergence': 'Convergence',

    // Scroll
    'scroll.new_messages': '↓ New Messages',

    // Page title
    'page.title': 'Discussion',

    // Language
    'lang.switch': '中',
    'lang.name': 'English',
  },
};

// Current language (default: zh-CN)
let _lang = 'zh-CN';

/**
 * Detect language from browser or localStorage.
 */
export function detectLanguage() {
  // Check localStorage first
  try {
    const saved = localStorage.getItem('rt_lang');
    if (saved && translations[saved]) return saved;
  } catch { /* no localStorage */ }

  // Check browser language
  const nav = navigator.language || navigator.userLanguage || 'zh-CN';
  if (nav.startsWith('zh')) return 'zh-CN';
  return 'en-US';
}

/**
 * Set current language.
 */
export function setLang(lang) {
  if (!translations[lang]) return;
  _lang = lang;
  try { localStorage.setItem('rt_lang', lang); } catch { /* no localStorage */ }
}

/**
 * Get current language code.
 */
export function getLang() {
  return _lang;
}

/**
 * Translate a key with optional parameter substitution.
 * @param {string} key - Translation key (e.g. 'round.discussion')
 * @param {Object} [params] - Parameters to substitute (e.g. { n: 3 })
 * @returns {string}
 */
export function t(key, params) {
  const dict = translations[_lang] || translations['zh-CN'];
  let str = dict[key] ?? translations['zh-CN'][key] ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), v);
    }
  }
  return str;
}

/**
 * Initialize i18n. Call once at startup.
 */
export function initI18n() {
  _lang = detectLanguage();
  return _lang;
}

/**
 * Get all available language codes.
 */
export function availableLanguages() {
  return Object.keys(translations);
}
