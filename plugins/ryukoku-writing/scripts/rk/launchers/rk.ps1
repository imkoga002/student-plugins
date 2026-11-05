# rk.ps1 - ryukoku-writing project command for PowerShell (unofficial). See rk (POSIX) for why it runs the
# installed plugin's code, located through $HOME\.ryukoku-writing\plugin-root, outside the project.
# PowerShell's default execution policy may refuse to run .ps1 files; then use .\rk.cmd setup instead (README).
# Not tried on a Windows machine yet.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$h = if ($env:RK_STATE_HOME) { $env:RK_STATE_HOME } else { Join-Path $env:USERPROFILE ".ryukoku-writing" }
$root = ""
$f = Join-Path $h "plugin-root"
if (Test-Path $f) { $root = "$(Get-Content $f -TotalCount 1)".Trim() }
$script = Join-Path $here "tools/rk/rk.py"
if ($root) {
  $cand = Join-Path $root "scripts/rk/rk.py"
  if (Test-Path $cand) { $script = $cand }
}
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 -I -B $script --project $here @args
} else {
  & python -I -B $script --project $here @args
}
exit $LASTEXITCODE
