/** "Show in Finder" on macOS, "Show in Explorer" on Windows. */
export function revealLabel(platform: string): string {
  if (platform === 'darwin') return 'Show in Finder'
  if (platform === 'win32') return 'Show in Explorer'
  return 'Show in folder'
}
