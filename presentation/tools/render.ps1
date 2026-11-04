<#
.SYNOPSIS
  Render the deck with Microsoft PowerPoint: PDF review copy and/or 1920x1080 PNG of every slide (for QA).
.EXAMPLE
  .\render.ps1 -Pptx ..\ProofCam_Meta_Global_AI_Hackathon.pptx -Pdf ..\ProofCam_Presentation.pdf -PngDir ..\previews
#>
param([Parameter(Mandatory)][string]$Pptx, [string]$Pdf, [string]$PngDir, [int]$Width = 1920, [int]$Height = 1080)
$ErrorActionPreference = "Stop"
$Pptx = (Resolve-Path $Pptx).Path
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($Pptx, -1, 0, 0)   # read-only, no window
    if ($Pdf) {
        $Pdf = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Pdf)
        $pres.SaveAs($Pdf, 32)                          # ppSaveAsPDF
        "PDF: $Pdf"
    }
    if ($PngDir) {
        $PngDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($PngDir)
        New-Item -ItemType Directory -Force $PngDir | Out-Null
        foreach ($s in $pres.Slides) {
            $s.Export((Join-Path $PngDir ("slide_{0:D2}.png" -f $s.SlideIndex)), "PNG", $Width, $Height)
        }
        "PNG: $($pres.Slides.Count) slides -> $PngDir"
    }
    $pres.Close()
}
finally {
    $ppt.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
}
