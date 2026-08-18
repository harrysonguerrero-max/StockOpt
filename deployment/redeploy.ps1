# AWS CLI v2 pasa las salidas largas por un paginador que se detiene con
# "-- MORE --" esperando una tecla, y deja el script colgado.
$env:AWS_PAGER = ""

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function New-ZipDeCarpeta {
    <#
    .SYNOPSIS
        Comprime una carpeta escribiendo las rutas con barra normal.

    .DESCRIPTION
        En Windows PowerShell 5.1 ni Compress-Archive ni
        ZipFile::CreateFromDirectory respetan el formato ZIP: guardan las rutas
        con la barra invertida de Windows. Quien descomprime en Linux —CodeBuild
        y Amplify— no ve carpetas sino archivos llamados "app\main.py", asi que
        el build no encuentra el codigo y el sitio sale vacio.

        Por eso se anaden las entradas de una en una, fijando el nombre a mano.
    #>
    param(
        [Parameter(Mandatory)][string]$Origen,
        [Parameter(Mandatory)][string]$Destino
    )

    $barra = [char]92
    if (Test-Path $Destino) { [System.IO.File]::Delete($Destino) }

    # Get-Item y no Resolve-Path: en carpetas bajo %TEMP%, Resolve-Path devuelve
    # la forma corta 8.3 ("C:\Users\HARRYS~1\...") mientras Get-ChildItem
    # devuelve FullName en forma larga. Restar longitudes entre las dos cortaba
    # doce caracteres antes de tiempo y dejaba media carpeta pegada al nombre de
    # cada entrada, asi que CodeBuild no encontraba buildspec.yml en la raiz.
    $raiz = (Get-Item -LiteralPath $Origen).FullName.TrimEnd($barra)
    $zip = [System.IO.Compression.ZipFile]::Open($Destino, 'Create')
    try {
        foreach ($archivo in Get-ChildItem -LiteralPath $raiz -Recurse -File -Force) {
            $relativa = $archivo.FullName.Substring($raiz.Length + 1).Replace($barra, '/')
            [void][System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $zip, $archivo.FullName, $relativa)
        }
    } finally {
        $zip.Dispose()
    }

    if (-not (Test-Path $Destino)) { throw "No se pudo crear $Destino" }
}

$accountId = "978439335053"
$region = "us-east-1"
$appName = "stockopt"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = Split-Path -Parent $scriptDir # Lulu
$frontendDir = Join-Path $projectPath "frontend"
# Vite escribe en frontend/dist. Apuntar a la raiz del proyecto dejaba el zip
# vacio o fallaba, porque ahi no hay ningun dist.
$distDir = Join-Path $frontendDir "dist"
$frontendZipName = "stockopt-frontend.zip"
$backendZipName = "stockopt-backend.zip"
$bucketName = "stockopt-bucket"
$branchName = "dev"
$codebuildProjectName = "stockopt-image-builder"
$clusterName = "stockopt-cluster"
$serviceName = "stockopt-service"


# ================= BUILD FRONTEND =================
Write-Host "Building frontend..."

Push-Location $frontendDir
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install failed." }

npm run build
if ($LASTEXITCODE -ne 0) { throw "npm build failed." }
Pop-Location

# ================= ZIP DEL FRONTEND =================
# Con Compress-Archive, que viene en PowerShell: `zip` dentro de WSL era una
# dependencia sin declarar y su ausencia tumbaba el despliegue.
Write-Host "Zipping dist..."

$zipFullPath = Join-Path $projectPath $frontendZipName
New-ZipDeCarpeta -Origen $distDir -Destino $zipFullPath

aws s3 cp $zipFullPath "s3://$bucketName/$frontendZipName"
if ($LASTEXITCODE -ne 0) { throw "Upload failed." }

# ================= PRESIGNED URL =================
$presignedUrl = aws s3 presign "s3://$bucketName/$frontendZipName" --expires-in 3600
if ($LASTEXITCODE -ne 0) { throw "Presign failed." }

# ================= DEPLOY =================
Write-Host "Starting deployment..."

$appId = aws amplify list-apps `
    --region $region `
    --query "apps[?name=='$appName'].appId | [0]" `
    --output text

aws amplify start-deployment `
    --region $region `
    --app-id $appId `
    --branch-name $branchName `
    --source-url $presignedUrl

if ($LASTEXITCODE -ne 0) { throw "Deployment failed to start." }

Write-Host "Deployment triggered successfully."


Write-Host "Creating file $backendZipName..."

# Compress-Archive aplana el arbol si se le pasa una lista de archivos, y
# CodeBuild necesita encontrar el buildspec en la raiz. De ahi la carpeta de
# paso con robocopy, que si sabe excluir directorios.
$backendZipPath = Join-Path $projectPath $backendZipName
if (Test-Path $backendZipPath) { Remove-Item $backendZipPath -Force }

$staging = Join-Path $env:TEMP "supplyopt-backend-zip"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }

robocopy $projectPath $staging /E /NFL /NDL /NJH /NJS /NP `
    /XD .venv .git frontend node_modules __pycache__ .pytest_cache .ruff_cache `
    /XF *.pyc *.zip .env | Out-Null

# Robocopy usa 0-7 para exito; sin normalizarlo se leeria como fallo.
if ($LASTEXITCODE -ge 8) { throw "Robocopy fallo al preparar el zip del backend." }
$global:LASTEXITCODE = 0

New-ZipDeCarpeta -Origen $staging -Destino $backendZipPath
Remove-Item $staging -Recurse -Force

Write-Host "$backendZipName created successfully."

# ========================
# Subir a S3
# ========================
Write-Host "Uploading $backendZipName to S3..."

aws s3 cp "$projectPath\$backendZipName" "s3://$bucketName/$backendZipName" --region $region

if ($LASTEXITCODE -ne 0) { throw "S3 upload failed." }

Write-Host "File $backendZipName uploaded to S3."

# ========================
# Iniciar CodeBuild
# ========================
Write-Host "Initiating CodeBuild project..."

$buildId = aws codebuild start-build `
    --project-name $codebuildProjectName `
    --region $region `
    --query 'build.id' `
    --output text

if (-not $buildId) {
    Write-Error "Unable to start CodeBuild project."
    throw "Unable to start CodeBuild project."}

Write-Host "Build initiated: $buildId"

Write-Host "Check progress at: https://$region.console.aws.amazon.com/codesuite/codebuild/$accountId/projects/$codebuildProjectName/build/$codebuildProjectName"

# ========================
# Esperar CodeBuild
# ========================
function Wait-CodeBuild {
    param (
        [string]$BuildId,
        [int]$PollSeconds = 30
    )

    while ($true) {
        $status = aws codebuild batch-get-builds `
            --ids $BuildId `
            --query 'builds[0].buildStatus' `
            --output text

        Write-Host "CodeBuild status: $status"

        switch ($status) {
            "SUCCEEDED" { return 0 }
            "FAILED"    { return 1 }
            "FAULT"     { return 1 }
            "STOPPED"   { return 1 }
            "TIMED_OUT" { return 1 }
        }

        Start-Sleep -Seconds $PollSeconds
    }
}

$result = Wait-CodeBuild -BuildId $buildId

if ($result -ne 0) {
    Write-Error "CodeBuild ended with error"
    throw "CodeBuild ended with error"
}

Write-Host "CodeBuild completed successfully."

# ========================
# Esperar ECS deployment
# ========================
Write-Host "Waiting for ECS deployment to complete..."
Write-Host "Check progress at: https://$region.console.aws.amazon.com/ecs/v2/clusters/$clusterName/services/$serviceName/deployments?region=$region"

aws ecs wait services-stable `
    --cluster $clusterName `
    --services $serviceName `
    --region $region

if ($LASTEXITCODE -ne 0) { throw "ECS deployment failed." }

if ($LASTEXITCODE -ne 0) { throw "ECS deployment failed." }

aws application-autoscaling register-scalable-target `
    --service-namespace ecs `
    --scalable-dimension ecs:service:DesiredCount `
    --resource-id service/$clusterName/$serviceName `
    --min-capacity 0 --max-capacity 1

IF ($LASTEXITCODE -ne 0) { throw "Autoscaling registration failed." }

aws application-autoscaling put-scheduled-action `
    --service-namespace ecs `
    --scheduled-action-name TurnOnWeekdays `
    --resource-id service/$clusterName/$serviceName `
    --scalable-dimension ecs:service:DesiredCount `
    --schedule "cron(0 15 ? * MON-FRI *)" `
    --scalable-target-action MinCapacity=1,MaxCapacity=1

if ($LASTEXITCODE -ne 0) { throw "Autoscaling scheduled action TurnOnWeekdays failed." }

aws application-autoscaling put-scheduled-action `
    --service-namespace ecs `
    --scheduled-action-name TurnOffWeekdays `
    --resource-id service/$clusterName/$serviceName `
    --scalable-dimension ecs:service:DesiredCount `
    --schedule "cron(0 23 ? * MON-FRI *)" `
    --scalable-target-action MinCapacity=0,MaxCapacity=0

if ($LASTEXITCODE -ne 0) { throw "Autoscaling scheduled action TurnOffWeekdays failed." }

Write-Host "ECS deployment completed successfully."

# ========================
# Fin
# ========================
Write-Host "Deployment completed successfully."
