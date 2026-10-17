const guard = async ($, e, next) => {
  const root = $.session.root()
  if (!e.file_path.startsWith(root + '/')) return { deny: 'outside the worktree; edit files under ' + root }
  return next(e)
}

export function register(on) {
  // 가드가 던지면 건너뛰어 편집이 통과하므로, 실패하면 거부하도록 .catch를 건다.
  on('tool.call', { tool: ['Edit', 'Write'] }, (...args) =>
    guard(...args).catch(() => ({ deny: 'guard failed; refusing the edit' })))
}
