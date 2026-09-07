$fixtureDir = Join-Path (Get-Location) "tests\fixtures"
New-Item -ItemType Directory -Force -Path $fixtureDir | Out-Null

Add-Type -AssemblyName System.Drawing

$width = 1800
$height = 1200
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

$graphics.Clear([System.Drawing.Color]::FromArgb(245, 248, 252))
$navy = [System.Drawing.Color]::FromArgb(15, 32, 58)
$blue = [System.Drawing.Color]::FromArgb(31, 95, 160)
$ink = [System.Drawing.Color]::FromArgb(25, 35, 50)
$muted = [System.Drawing.Color]::FromArgb(75, 91, 112)

$whiteBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
$navyBrush = New-Object System.Drawing.SolidBrush($navy)
$blueBrush = New-Object System.Drawing.SolidBrush($blue)
$inkBrush = New-Object System.Drawing.SolidBrush($ink)
$mutedBrush = New-Object System.Drawing.SolidBrush($muted)

$graphics.FillRectangle($navyBrush, 0, 0, $width, 170)
$graphics.FillRectangle($blueBrush, 0, 170, $width, 12)

$titleFont = New-Object System.Drawing.Font("Arial", 34, [System.Drawing.FontStyle]::Bold)
$sectionFont = New-Object System.Drawing.Font("Arial", 23, [System.Drawing.FontStyle]::Bold)
$bodyFont = New-Object System.Drawing.Font("Arial", 20, [System.Drawing.FontStyle]::Regular)
$smallFont = New-Object System.Drawing.Font("Arial", 17, [System.Drawing.FontStyle]::Bold)

$graphics.DrawString("SUDARSHAN PIPELINE TEST CASE", $titleFont, $whiteBrush, 55, 35)
$graphics.DrawString("SYNTHETIC TEST DATA - NOT OPERATIONAL INTELLIGENCE", $smallFont, $whiteBrush, 58, 105)
$graphics.DrawString("Case: Coastal Flood Response Readiness", $sectionFont, $blueBrush, 65, 225)
$graphics.DrawString("Source: Field Coordination Brief  |  Date: 15 August 2026  |  Classification: RESTRICTED", $smallFont, $mutedBrush, 65, 275)

$lines = @(
    "Situation",
    "Heavy rainfall has affected three coastal districts. This synthetic case tests",
    "whether one source can be transformed into a briefing deck, an infographic,",
    "and a narrated video.",
    "Verified observations",
    "• 142 mm rainfall recorded in the last 24 hours.",
    "• Three transport corridors have restricted movement.",
    "• Two temporary shelters are operating near the eastern transit zone.",
    "• Emergency supplies are expected to cover 72 hours.",
    "Recommended focus",
    "Prioritize shelter capacity, route status, supply coverage, and a clear public-information sequence.",
    "Output request",
    "Create a concise PPTX, a visual infographic, and a 60-second explainer video",
    "with story, storyboard, narration, scene visuals, and audio."
)

$y = 350
foreach ($line in $lines) {
    if ($line -in @("Situation", "Verified observations", "Recommended focus", "Output request")) {
        $graphics.DrawString($line, $sectionFont, $blueBrush, 65, $y)
        $y += 42
    } else {
        $graphics.DrawString($line, $bodyFont, $inkBrush, 65, $y)
        $y += 39
    }
    if ($line -eq "Verified observations") { $y += 8 }
}

$graphics.DrawString("Synthetic source prepared for Sudarshan ingestion and multi-pipeline testing.", $smallFont, $mutedBrush, 65, 1115)

$outputPath = Join-Path $fixtureDir "pipeline-source-brief.png"
$bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)

$graphics.Dispose()
$bitmap.Dispose()
Write-Output $outputPath
