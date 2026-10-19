# Aplica as mudanças do backend SÓ se os arquivos no PC não mudaram desde a cópia (17/10 20:25).
# Uso: coloque aplicar.ps1 e backend_alterado.zip na mesma pasta e rode:  powershell -ExecutionPolicy Bypass -File aplicar.ps1
$p = "C:\Users\grazi\chat  com rag"
$esperado = @{
 "backend\.env.example"="5c6995d9677121b1"; "backend\modal_app.py"="0601a1082b2d1c59"; "backend\rag\pipeline.py"="55146380050af287";
 "backend\rag\prompts.py"="970cdba23a730e11"; "backend\rag\retrieval.py"="4db03afff910ba35"; "backend\rag\schemas.py"="02b4acfd7b2a5251";
 "backend\rag\settings.py"="bf2c9b1d78d84d72" }
$ok = $true
foreach ($f in $esperado.Keys) { $h=(Get-FileHash -Algorithm SHA256 (Join-Path $p $f)).Hash.ToLower().Substring(0,16); if ($h -ne $esperado[$f]) { Write-Output "MUDOU desde a copia: $f"; $ok=$false } }
foreach ($f in @("backend\rag\triage_aids.py","backend\tests\test_melhorias.py")) { if (Test-Path (Join-Path $p $f)) { Write-Output "JA EXISTE: $f"; $ok=$false } }
if (-not $ok) { Write-Output "Nada foi alterado."; exit 1 }
Expand-Archive -Force -Path (Join-Path $PSScriptRoot "backend_alterado.zip") -DestinationPath $p
Write-Output "Backend atualizado (9 arquivos)."
