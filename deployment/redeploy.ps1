$accountId = "978439335053"
$region = "us-east-1"
$appName = "stockopt"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPath = Split-Path -Parent $scriptDir # Lulu
$frontendDir = Join-Path $projectPath "frontend"
$distDir = Join-Path $projectPath "dist"
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

# ================= ZIP WITH WSL =================
Write-Host "Zipping dist..."

wsl -d Ubuntu --cd "$distDir" --exec bash -lc "zip -r '$frontendZipName' . -x '.venv/*' -x '.venv/**' -x '*/.venv/*' -x '*/.venv/**' -x '__pycache__/*' -x '*/__pycache__/*' -x '*.pyc' -x '.git/*' -x '$frontendZipName'"


if ($LASTEXITCODE -ne 0) { throw "Zip failed." }

$zipFullPath = Join-Path $distDir $frontendZipName

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

# Limpiar ZIP previo
wsl -d Ubuntu --cd "$projectPath" --exec bash -lc "rm -f '$backendZipName'"

# Crear ZIP
wsl -d Ubuntu --cd "$projectPath" --exec bash -lc "zip -r '$backendZipName' . -x '.venv/*' -x '.venv/**' -x '*/.venv/*' -x '*/.venv/**' -x '__pycache__/*' -x '*/__pycache__/*' -x '*.pyc' x '.git/*' -x '$backendZipName' -x 'frontend/*' -x 'frontend/**' -x '*/frontend/*' -x '*/frontend/**'"


# Verificar ZIP
if (-not (Test-Path "$projectPath\$backendZipName")) {
    Write-Error "File $backendZipName was not created."
    throw "File $backendZipName was not created."
}

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
