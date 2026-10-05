# Hook SessionStart: injeta a memória do projeto (vault Obsidian) no contexto da sessão.
$vault = 'C:\Users\guilh\Documents\Vaults\dev-crew-vault'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Write-Output '# Memoria do projeto (vault Obsidian: C:/Users/guilh/Documents/Vaults/dev-crew-vault)'
foreach ($f in '_index.md', 'sessions\_recent.md') {
    $p = Join-Path $vault $f
    if (Test-Path $p) { Get-Content -Raw -Encoding UTF8 $p }
}
