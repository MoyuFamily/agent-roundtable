/**
 * Simple i18n module for Roundtable Web Viewer.
 * Supports zh-CN (default) and en-US.
 *
 * Loaded as a regular <script> — attaches to window.__RT_I18N__.
 * Use t(), setLang(), getLang(), initI18n() from global scope.
 */

(function () {
  'use strict';

  const translations = {
    'zh-CN': {
      // Header status
      statusWaiting: '等待中',
      statusActive: '讨论中',
      statusConcluded: '已结束',

      // Connection
      connConnected: '已连接',
      connReconnecting: '重连中…',
      connDisconnected: '已断开',

      // Waiting state
      waitingTitle: '讨论即将开始…',
      waitingSubtitle: '发言将会实时显示在这里',

      // Participants
      participants: '参与者',
      participantsCount: '位参与者',

      // Speeches
      speeches: '发言',
      speechesCount: '条发言',
      count: '条',
      speechComplete: '发言完成',

      // Rounds
      round0Speech: '开场发言',
      roundDiscussion: '第 {round} 轮讨论',
      roundN: '第 {round} 轮',
      rounds: '轮次',
      roundViewpointSummary: '第 {round} 轮观点汇总',

      // Conclusions & viewpoints
      conclusion: '结论',
      convergence: '收敛度',
      consensusPoints: '✅ 共识观点',
      disagreementPoints: '⚡ 分歧观点',
      finalConsensus: '✅ 最终共识',
      remainingDisagreement: '⚡ 保留分歧',
      none: '暂无',
      coordinator: '协调者',

      // Share
      share: '分享',
      shareTitle: '📋 分享链接',
      shareHint: '任何人通过此链接可查看讨论',
      copy: '复制',
      copied: '✓ 已复制',
      copyLink: '复制链接',
      shareRevoke: '⚠️ 撤销链接',
      shareRevoked: '链接已撤销',
      shareMobile: '分享讨论',

      // Revoke modal
      revokeTitle: '确认撤销链接？',
      revokeDesc: '撤销后，所有通过此链接的访问将在 5 秒内失效，且不可恢复。',
      revokeCancel: '取消',
      confirmRevoke: '确认撤销',
      revoking: '撤销中…',
      revokeFailed: '撤销失败，请重试',
      networkError: '网络错误，请重试',

      // Revoked state
      revokedTitle: '此讨论链接已失效',
      revokedDesc: '创作者已撤销了此链接的访问权限',
      revokedBrand: 'Roundtable AI · 圆桌讨论',

      // Export
      exportBtn: '导出',
      exportMarkdown: 'Markdown',
      exportPdf: 'PDF',
      exportTitle: '导出讨论结果',
      exportDownloading: '正在生成…',
      exportFailed: '导出失败',

      // Password
      passwordTitle: '🔒 访问验证',
      passwordDesc: '此讨论需要密码才能查看',
      passwordPlaceholder: '请输入访问密码',
      passwordSubmit: '进入',
      passwordError: '密码错误，请重试',
      passwordRequired: '请输入密码',

      // Replay
      replayEntryTitle: '回放讨论全过程',
      replayBack: '返回',
      replay: '回放',

      // Scroll
      scrollNewMessages: '↓ 新消息',

      // Page title
      roundtableDiscussion: '圆桌讨论',
      pageTitle: '圆桌讨论',

      // Language
      langSwitch: 'EN',
      langName: '中文',
    },

    'en-US': {
      // Header status
      statusWaiting: 'Waiting',
      statusActive: 'Active',
      statusConcluded: 'Concluded',

      // Connection
      connConnected: 'Connected',
      connReconnecting: 'Reconnecting…',
      connDisconnected: 'Disconnected',

      // Waiting state
      waitingTitle: 'Discussion starting soon…',
      waitingSubtitle: 'Speeches will appear here in real-time',

      // Participants
      participants: 'Participants',
      participantsCount: 'participants',

      // Speeches
      speeches: 'speeches',
      speechesCount: 'speeches',
      count: '',
      speechComplete: 'Done',

      // Rounds
      round0Speech: 'Opening',
      roundDiscussion: 'Round {round} Discussion',
      roundN: 'Round {round}',
      rounds: 'rounds',
      roundViewpointSummary: 'Round {round} Summary',

      // Conclusions & viewpoints
      conclusion: 'Conclusion',
      convergence: 'Convergence',
      consensusPoints: '✅ Consensus',
      disagreementPoints: '⚡ Disagreement',
      finalConsensus: '✅ Final Consensus',
      remainingDisagreement: '⚡ Remaining Disagreement',
      none: 'None',
      coordinator: 'Coordinator',

      // Share
      share: 'Share',
      shareTitle: '📋 Share Link',
      shareHint: 'Anyone with this link can view the discussion',
      copy: 'Copy',
      copied: '✓ Copied!',
      copyLink: 'Copy Link',
      shareRevoke: '⚠️ Revoke Link',
      shareRevoked: 'Link Revoked',
      shareMobile: 'Share Discussion',

      // Revoke modal
      revokeTitle: 'Revoke Link?',
      revokeDesc: 'Once revoked, all access via this link will be invalidated within 5 seconds and cannot be recovered.',
      revokeCancel: 'Cancel',
      confirmRevoke: 'Revoke',
      revoking: 'Revoking…',
      revokeFailed: 'Revoke failed, please try again',
      networkError: 'Network error, please try again',

      // Revoked state
      revokedTitle: 'This link has been revoked',
      revokedDesc: 'The creator has revoked access to this link',
      revokedBrand: 'Roundtable AI · Discussion',

      // Export
      exportBtn: 'Export',
      exportMarkdown: 'Markdown',
      exportPdf: 'PDF',
      exportTitle: 'Export Discussion',
      exportDownloading: 'Generating…',
      exportFailed: 'Export failed',

      // Password
      passwordTitle: '🔒 Access Verification',
      passwordDesc: 'This discussion requires a password to view',
      passwordPlaceholder: 'Enter access password',
      passwordSubmit: 'Enter',
      passwordError: 'Incorrect password, please try again',
      passwordRequired: 'Please enter a password',

      // Replay
      replayEntryTitle: 'Replay Full Discussion',
      replayBack: 'Back',
      replay: 'Replay',

      // Scroll
      scrollNewMessages: '↓ New Messages',

      // Page title
      roundtableDiscussion: 'Discussion',
      pageTitle: 'Discussion',

      // Language
      langSwitch: '中',
      langName: 'English',
    },
  };

  let _lang = 'zh-CN';

  function detectLanguage() {
    try {
      const saved = localStorage.getItem('rt_lang');
      if (saved && translations[saved]) return saved;
    } catch { /* no localStorage */ }
    const nav = navigator.language || navigator.userLanguage || 'zh-CN';
    if (nav.startsWith('zh')) return 'zh-CN';
    return 'en-US';
  }

  function setLang(lang) {
    if (!translations[lang]) return;
    _lang = lang;
    try { localStorage.setItem('rt_lang', lang); } catch { /* no localStorage */ }
  }

  function getLang() {
    return _lang;
  }

  function t(key, params) {
    const dict = translations[_lang] || translations['zh-CN'];
    let str = dict[key] ?? translations['zh-CN'][key] ?? key;
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        str = str.replace(new RegExp('\\{' + k + '\\}', 'g'), v);
      }
    }
    return str;
  }

  function initI18n() {
    _lang = detectLanguage();
    return _lang;
  }

  function availableLanguages() {
    return Object.keys(translations);
  }

  // Expose to global scope
  window.__RT_I18N__ = { t, setLang, getLang, initI18n, detectLanguage, availableLanguages };
  // Convenience globals
  window.t = t;
  window.setLang = setLang;
  window.getLang = getLang;
  window.initI18n = initI18n;
})();
