param(
    [ValidateSet('full','scalability')][string]$Mode = 'full',
    [ValidateRange(1,4)][int]$Workers = 1,
    [ValidateRange(1,10000)][int]$SeedCount = 30,
    [int]$SeedStart = 9000,
    [ValidateRange(1,100000000)][double]$Duration = 20000,
    [ValidateRange(2,10000)][int]$NumNodes = 50,
    [string]$Sizes = '25,50,100,150,200',
    [string]$Lambdas = '2,4,6,8,10,12',
    [string]$OutputDir = '',
    [ValidateRange(0,1)][double]$LinkProb = 0.35,
    [ValidateRange(0,1)][double]$VnrLinkProb = 0.4,
    [ValidateRange(0.000001,100000000)][double]$LifetimeMean = 500,
    [ValidateRange(0,100000000)][double]$MaxDelay = 25,
    [ValidateRange(1,1000000)][int]$MaxHops = 8,
    [ValidateRange(0,100000000)][double]$PIdle = 150,
    [ValidateRange(0,100000000)][double]$PPeak = 350,
    [ValidateRange(0,100000000)][double]$PLink = 5,
    [ValidateRange(0,100000000)][double]$BootEnergyJoules = 50,
    [switch]$LegacyOnly
)
$ErrorActionPreference = 'Stop'
if (-not $OutputDir) { $OutputDir = 'results/confirmation_' + $Mode }
$paperSeeds = ($SeedStart..($SeedStart + $SeedCount - 1)) -join ','
$simulationArgs = @('--mode',$Mode,'--duration',"$Duration",'--seeds',$paperSeeds,
                    '--workers',"$Workers",'--include-pso','--include-ablations',
                    '--output-dir',$OutputDir,'--link-prob',"$LinkProb",
                    '--vnr-link-prob',"$VnrLinkProb",'--lifetime-mean',"$LifetimeMean",
                    '--max-delay',"$MaxDelay",'--max-hops',"$MaxHops",'--p-idle',"$PIdle",
                    '--p-peak',"$PPeak",'--p-link',"$PLink",'--boot-energy-joules',"$BootEnergyJoules")
if (-not $LegacyOnly) { $simulationArgs += '--include-reference-baselines' }
if ($Mode -eq 'full') {
    $simulationArgs += @('--num-nodes',"$NumNodes",'--lambdas',$Lambdas)
} else {
    $simulationArgs += @('--sizes',$Sizes)
}
& (Join-Path $PSScriptRoot 'run.ps1') @simulationArgs
exit $LASTEXITCODE
