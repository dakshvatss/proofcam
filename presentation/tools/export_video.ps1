<#
.SYNOPSIS
  Export the finished deck (recordings inserted, narration recorded) to a 1080p MP4 with Microsoft PowerPoint.
  Uses each slide's timing (Transitions -> After) and any narration recorded with Slide Show -> Record.
  Hidden slides are skipped. Refuses to overwrite an existing file.
.EXAMPLE
  .\export_video.ps1 -Pptx ..\ProofCam_Meta_Global_AI_Hackathon.pptx -Out ..\ProofCam_Final_Demo.mp4
#>
param([Parameter(Mandatory)][string]$Pptx, [Parameter(Mandatory)][string]$Out, [int]$Height = 1080, [int]$Fps = 30)
$ErrorActionPreference = "Stop"
$Pptx = (Resolve-Path $Pptx).Path
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
if (Test-Path $Out) { throw "$Out already exists; choose another name or delete it first" }
$ppt = New-Object -ComObject PowerPoint.Application
try {
    $pres = $ppt.Presentations.Open($Pptx, -1, 0, 0)
    # The video is slides 1-14 only: the appendix (15+) is hidden for this export, in memory (the file is read-only).
    foreach ($s in $pres.Slides) { if ($s.SlideIndex -gt 14) { $s.SlideShowTransition.Hidden = -1 } }
    # The video plays each slide's fade (Duration) in addition to its timer (AdvanceTime).
    $secs = 0; foreach ($s in $pres.Slides) { $t = $s.SlideShowTransition; if ($t.Hidden -eq 0) { $secs += $t.AdvanceTime + $t.Duration } }
    "Planned length from slide timings: {0}:{1:D2}" -f [math]::Floor($secs / 60), [int]($secs % 60)
    if ($secs -gt 178) { Write-Warning "Longer than 2:58: shorten slide timings (Transitions -> After) before uploading." }
    $placeholders = foreach ($s in $pres.Slides) { foreach ($sh in $s.Shapes) { if ($sh.Name -like "VIDEO PLACEHOLDER*" -and $s.SlideShowTransition.Hidden -eq 0) { "slide $($s.SlideIndex): $($sh.Name)" } } }
    if ($placeholders) { Write-Warning ("Placeholders still present (insert the recordings first?):`n  " + ($placeholders -join "`n  ")) }
    $pres.CreateVideo($Out, $true, 5, $Height, $Fps, 90)   # use recorded timings + narration, 1080p
    while ($pres.CreateVideoStatus -in 1, 2) { Start-Sleep -Seconds 3 }   # in progress / queued
    if ($pres.CreateVideoStatus -ne 3) { throw "PowerPoint reported export status $($pres.CreateVideoStatus) (4 = failed)" }
    $pres.Close()
    "Video written: $Out ($([math]::Round((Get-Item $Out).Length / 1MB, 1)) MB). Check the duration is under 3:00."
}
finally {
    $ppt.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($ppt)
}
