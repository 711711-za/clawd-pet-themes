$OutputEncoding=[Text.Encoding]::UTF8; [Console]::InputEncoding=[Text.Encoding]::UTF8
$codex = Join-Path (Get-AppxPackage OpenAI.Codex).InstallLocation 'app\resources\codex.exe'
Get-Content -Raw -Encoding UTF8 'C:\Users\18533\Desktop\桌宠\clawd-themes\honami\codex-job\prompt-sit.txt' | & $codex exec --skip-git-repo-check --sandbox workspace-write -C 'C:\Users\18533\Desktop\桌宠\clawd-themes\honami' --image 'C:\Users\18533\Desktop\桌宠\clawd-themes\honami\raw\sheet-A-v5.png' --image 'C:\Users\18533\Desktop\桌宠\clawd-themes\honami\raw\sheet-R-v5.png' - *> 'C:\Users\18533\Desktop\桌宠\clawd-themes\honami\codex-job\sit.log'

