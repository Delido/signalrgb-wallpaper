# GPU utilisation per process, averaged over a few samples.
#
# Used to answer "why does the wallpaper cost N % GPU": the Lively pages
# show up as msedgewebview2, Wallpaper Engine as wallpaper32/64 + CEF
# helpers, and DWM (the desktop compositor) pays for every repaint the
# wallpaper makes. Compare a run before and after a change.
#
# Usage:  pwsh tools\gpu_by_process.ps1 [-Seconds 10] [-Min 0.2]
param([int]$Seconds = 10, [double]$Min = 0.2)

$n = [math]::Max(1, [int]($Seconds / 2))
$s = Get-Counter '\GPU Engine(*)\Utilization Percentage' -SampleInterval 2 -MaxSamples $n
$agg = @{}
foreach ($c in $s.CounterSamples) {
    if ($c.InstanceName -match 'pid_(\d+).*engtype_(\w+)') {
        $k = "$($Matches[1])|$($Matches[2])"
        $agg[$k] = ($agg[$k] + $c.CookedValue)
    }
}
$rows = $agg.GetEnumerator() | ForEach-Object {
    $p, $e = $_.Key -split '\|'
    [pscustomobject]@{ Pid = [int]$p; Engine = $e; Avg = [math]::Round($_.Value / $n, 2) }
} | Where-Object Avg -gt $Min | Sort-Object Avg -Descending
$rows | ForEach-Object {
    $name = (Get-Process -Id $_.Pid -ErrorAction SilentlyContinue).ProcessName
    $_ | Add-Member Name $name -PassThru
} | Format-Table Name, Pid, Engine, Avg -AutoSize | Out-String -Width 200
$total = ($rows | Measure-Object Avg -Sum).Sum
"Sum of listed: {0:N2} %  ({1} samples over {2} s)" -f $total, $n, ($n * 2)
