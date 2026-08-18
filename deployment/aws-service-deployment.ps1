# Despliegue completo desde cero: Amplify, ALB, API Gateway, ECS, ECR y CodeBuild.
#
# Si algo falla, el bloque catch del final borra todo lo que el script toca. Eso
# deja la cuenta limpia para volver a lanzar, que es justo lo que hace falta
# cuando el fallo ocurre a mitad: los recursos a medias provocan choques de
# nombres en la siguiente corrida y hay que borrarlos a mano uno por uno.

# ================= STRICT MODE =================
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# AWS CLI v2 pasa las salidas largas por un paginador, que se detiene con
# "-- MORE --" esperando una tecla. En un script eso no informa de nada y deja
# el despliegue colgado hasta que alguien pulsa Enter.
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

try {

    # ================= CONFIG =================
    $accountId = "978439335053"
    $region = "us-east-1"
    $appName = "stockopt"
    $branchName = "dev"
    $clusterName = "stockopt-cluster"
    $serviceName = "stockopt-service"
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $projectPath = Split-Path -Parent $scriptDir
    $frontendDir = Join-Path $projectPath "frontend"
    $distDir = Join-Path $frontendDir "dist"
    $frontendZipName = "stockopt-frontend.zip"
    $backendZipName = "stockopt-backend.zip"
    $vpcId = "vpc-05a9a5150a57a296f"
    $subnet1a = "subnet-030984325b2511d89"
    $subnet1b = "subnet-028fca817e4f807be"
    $albSg = "sg-00ebae601f4d7894d"
    $ecsSg = "sg-0cb8c7ae12c8b565d"
    $taskDefFile = ".\ecs-task-definition.json"
    $logGroupName = "/aws/ecs/$appName-logs"
    $bucketName = "stockopt-bucket"
    $repoName = "stockopt-repository"
    $codebuildProjectName = "stockopt-image-builder"
    $codebuildServiceRoleName = "${codebuildProjectName}-service-role"
    $ecsTaskRoleName = "stockopt-ecs-task-role"
    $ecsExecutionRoleName = "stockopt-ecs-execution-role"

    # ================= CLEANUP EXISTING AMPLIFY APP =================
    Write-Host "Checking for existing Amplify app named $appName..."

    $existingAppId = aws amplify list-apps `
        --region $region `
        --query "apps[?name=='$appName'].appId | [0]" `
        --output text

    if ($existingAppId -and $existingAppId -ne "None") {
        Write-Host "Found existing Amplify app with ID: $existingAppId. Deleting..."
        
        aws amplify delete-app `
            --app-id $existingAppId `
            --region $region

        if ($LASTEXITCODE -ne 0) { throw "Failed to delete existing Amplify app." }

        Write-Host "Deleted existing Amplify app. Waiting for deletion to complete..."
        
        # Wait until the app is deleted
        do {
            Start-Sleep -Seconds 5
            try {
                aws amplify get-app --app-id $existingAppId --region $region > $null 2>&1
                $appExists = $true
            } catch {
                # If get-app fails, assume the app no longer exists
                $appExists = $false
            }
        } while ($appExists)

        Write-Host "Existing Amplify app deletion complete."
    } else {
        Write-Host "No existing Amplify app found with name $appName."
    }

    # ================= CREATE AMPLIFY APP =================
    Write-Host "Creating Amplify app..."

    $responseJson = aws amplify create-app `
    --region $region `
    --name $appName `
    --platform WEB `
    --custom-rules '[{\"source\":\"/<*>\",\"target\":\"/index.html\",\"status\":\"404-200\"}]' `
    --cache-config type=AMPLIFY_MANAGED_NO_COOKIES `
    --job-config buildComputeType=STANDARD_8GB `
    --output json

    if ($LASTEXITCODE -ne 0) { throw "Amplify create-app failed." }

    $response = $responseJson | ConvertFrom-Json
    $appId = $response.app.appId

    if (-not $appId) { throw "App ID was not returned." }

    Write-Host "Amplify App Created with ID: $appId"

    $amplifyUrl = "https://${branchName}.$(aws amplify get-app `
        --app-id $appId `
        --region $region `
        --query "app.defaultDomain" `
        --output text)"

    # ================= CREATE BRANCH =================
    Write-Host "Creating branch..."

    aws amplify create-branch `
        --region $region `
        --app-id $appId `
        --branch-name $branchName `
        --stage PRODUCTION

    if ($LASTEXITCODE -ne 0) { throw "Branch creation failed." }

    # ================= CREATE S3 BUCKET =================
    Write-Host "Creating S3 bucket: $bucketName"

    if ($region -eq "us-east-1") {
        aws s3api create-bucket `
            --bucket $bucketName `
            --region $region
    } else {
        aws s3api create-bucket `
            --bucket $bucketName `
            --region $region `
            --create-bucket-configuration LocationConstraint=$region
    }

    if ($LASTEXITCODE -ne 0) { throw "Bucket creation failed." }

    aws s3api wait bucket-exists --bucket $bucketName

    if ($LASTEXITCODE -ne 0) { throw "Bucket wait failed." }

    # ================= CREATE LOG GROUP =================

    Write-Host "Creating CloudWatch log group..."

    aws logs create-log-group `
    --log-group-name $logGroupName `
    --region $region

    if ($LASTEXITCODE -ne 0) { throw "Log group creation failed." }

    # CloudWatch Logs recibe las etiquetas como mapa plano, no como lista de
    # estructuras Key/Value. Con la forma larga interpretaba el primer token
    # como el mapa entero y el segundo le sobraba: "Unknown options".
    aws logs tag-log-group `
        --log-group-name $logGroupName `
        --tags Name=${appName}-logs,Project=${appName} `
        --region $region

    # ================= CREATE TARGET GROUP AND ALB =================

    Write-Host "Creating Target Group and ALB..."

    $tgArn = aws elbv2 create-target-group `
        --name "$appName-tg" `
        --protocol HTTP `
        --port 8000 `
        --target-type ip `
        --vpc-id $vpcId `
        --health-check-path "/" `
        --region $region `
        --query "TargetGroups[0].TargetGroupArn" `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "Target group creation failed." }

    aws elbv2 add-tags `
        --resource-arns $tgArn `
        --tags Key=Name,Value=${appName}-tg Key=Project,Value=${appName} `
        --region $region

    $albArn = aws elbv2 create-load-balancer `
        --name "${appName}-alb" `
        --subnets $subnet1a $subnet1b `
        --security-groups $albSg `
        --scheme internet-facing `
        --type application `
        --region $region `
        --query "LoadBalancers[0].LoadBalancerArn" `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "ALB creation failed." }

    aws elbv2 add-tags `
        --resource-arns $albArn `
        --tags Key=Name,Value=${appName}-alb Key=Project,Value=${appName} `
        --region $region

    aws elbv2 wait load-balancer-available `
        --load-balancer-arns $albArn `
        --region $region

    if ($LASTEXITCODE -ne 0) { throw "ALB did not become active." }

    aws elbv2 create-listener `
        --load-balancer-arn $albArn `
        --protocol HTTP `
        --port 80 `
        --default-actions Type=forward,TargetGroupArn=$tgArn `
        --region $region `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "Listener creation failed." }

    # ================= CREATE API GATEWAY =================

    write-Host "Creating API Gateway..."

    $albDns = aws elbv2 describe-load-balancers `
        --names "$appName-alb" `
        --region $region `
        --query "LoadBalancers[0].DNSName" `
        --output text

    $apiId = aws apigatewayv2 create-api `
        --name "$appName" `
        --protocol-type HTTP `
        --cors-configuration '{\"AllowOrigins\":[\"*\"],\"AllowMethods\":[\"GET\",\"POST\",\"PUT\",\"DELETE\",\"OPTIONS\",\"PATCH\",\"HEAD\"],\"AllowHeaders\":[\"*\"],\"ExposeHeaders\":[\"*\"],\"AllowCredentials\":false,\"MaxAge\":0}' `
        --region $region `
        --query "ApiId" `
        --output text


    if ($LASTEXITCODE -ne 0) { throw "API Gateway creation failed." }

    aws apigatewayv2 tag-resource `
        --resource-arn "arn:aws:apigateway:$region::/apis/$apiId" `
        --tags Name=${appName}-api-gateway,Project=${appName} `
        --region $region

    $rootIntegrationId = aws apigatewayv2 create-integration `
        --api-id $apiId `
        --integration-type HTTP_PROXY `
        --integration-method ANY `
        --integration-uri "http://${albDns}:80" `
        --payload-format-version 1.0 `
        --timeout-in-millis 30000 `
        --region $region `
        --query "IntegrationId" `
        --output text
    if ($LASTEXITCODE -ne 0) { throw "API Gateway integration creation failed." }

    $proxyIntegrationId = aws apigatewayv2 create-integration `
        --api-id $apiId `
        --integration-type HTTP_PROXY `
        --integration-method ANY `
        --integration-uri "http://${albDns}:80/{proxy}" `
        --payload-format-version 1.0 `
        --timeout-in-millis 30000 `
        --region $region `
        --query "IntegrationId" `
        --output text
    if ($LASTEXITCODE -ne 0) { throw "API Gateway proxy integration creation failed." }

    aws apigatewayv2 create-route `
        --api-id $apiId `
        --route-key "ANY /" `
        --authorization-type NONE `
        --target "integrations/$rootIntegrationId" `
        --region $region
    if ($LASTEXITCODE -ne 0) { throw "API Gateway root route creation failed." }

    aws apigatewayv2 create-route `
        --api-id $apiId `
        --route-key "ANY /{proxy+}" `
        --authorization-type NONE `
        --target "integrations/$proxyIntegrationId" `
        --region $region
    if ($LASTEXITCODE -ne 0) { throw "API Gateway proxy route creation failed." }

    aws apigatewayv2 create-stage `
        --api-id $apiId `
        --stage-name '$default' `
        --auto-deploy `
        --region $region
    if ($LASTEXITCODE -ne 0) { throw "API Gateway stage creation failed." }

    $apiEndpoint = aws apigatewayv2 get-api `
        --api-id $apiId `
        --region $region `
        --query "ApiEndpoint" `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "API Gateway endpoint retrieval failed." }

    Write-Host "API ID: $apiId"

    # ================= CREATE IAM ROLES =================
    
    Write-Host "Creating IAM roles..."

    Write-Host "Creating CodeBuild service role..."

    aws iam create-role `
        --role-name $codebuildServiceRoleName  `
        --assume-role-policy-document file://deployment/codebuild-trust-policy.json `
        --path "/service-role/" `
        --max-session-duration 3600
    
    if ($LASTEXITCODE -ne 0) { throw "CodeBuild service role creation failed." }

    aws iam wait role-exists --role-name "$codebuildServiceRoleName"

    Write-Host "Attaching policies to CodeBuild service role..."

    aws iam attach-role-policy `
        --role-name "$codebuildServiceRoleName" `
        --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser

    if ($LASTEXITCODE -ne 0) { throw "Attaching ECR policy failed." }

    aws iam attach-role-policy `
        --role-name "$codebuildServiceRoleName" `
        --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
    
    if ($LASTEXITCODE -ne 0) { throw "Attaching S3 policy failed." }

    aws iam put-role-policy --role-name `
        "$codebuildServiceRoleName" `
        --policy-name "$codebuildProjectName-inline-policy" `
        --policy-document file://deployment/codebuild-inline-policy.json
    
    if ($LASTEXITCODE -ne 0) { throw "Attaching inline policy failed." }

    Write-Host "Creating ECS task execution role..."

    aws iam create-role `
        --role-name $ecsExecutionRoleName `
        --assume-role-policy-document file://deployment/task-role-trust-policy.json
    if ($LASTEXITCODE -ne 0) { throw "IAM role creation failed." }

    aws iam wait role-exists --role-name $ecsExecutionRoleName

    Write-Host "Attaching policies to ECS task execution role..."

    aws iam attach-role-policy `
        --role-name $ecsExecutionRoleName `
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

    if ($LASTEXITCODE -ne 0) { throw "Attaching execution role policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsExecutionRoleName `
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceRole

    if ($LASTEXITCODE -ne 0) { throw "Attaching container service role policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsExecutionRoleName `
        --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite

    if ($LASTEXITCODE -ne 0) { throw "Attaching Secrets Manager policy failed." }

    Write-Host "Creating ECS task role..."

    aws iam create-role `
        --role-name $ecsTaskRoleName `
        --assume-role-policy-document file://deployment/task-role-trust-policy.json

    if ($LASTEXITCODE -ne 0) { throw "IAM role creation failed." }

    aws iam wait role-exists --role-name $ecsTaskRoleName

    Write-Host "Attaching policies to ECS task role..."

    aws iam attach-role-policy `
        --role-name $ecsTaskRoleName `
        --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess

    if ($LASTEXITCODE -ne 0) { throw "Attaching ECR policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsTaskRoleName `
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

    if ($LASTEXITCODE -ne 0) { throw "Attaching task execution role policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsTaskRoleName `
        --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess

    if ($LASTEXITCODE -ne 0) { throw "Attaching EC2 full access policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsTaskRoleName `
        --policy-arn arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceRole

    if ($LASTEXITCODE -ne 0) { throw "Attaching container service role policy failed." }

    aws iam attach-role-policy `
        --role-name $ecsTaskRoleName `
        --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite

    if ($LASTEXITCODE -ne 0) { throw "Attaching Secrets Manager policy failed." }

    Start-Sleep -Seconds 15
    
    # ================= REGISTER TASK DEFINITION =================

    Write-Host "Registering ECS task definition..."

    $taskDefArn = aws ecs register-task-definition `
        --cli-input-json file://deployment/$taskDefFile `
        --region $region `
        --query "taskDefinition.taskDefinitionArn" `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "Task definition registration failed." }

    # ================= CREATE ECS CLUSTER =================

    Write-Host "Creating ECS cluster..."

    aws ecs create-cluster `
        --cluster-name $clusterName `
        --capacity-providers FARGATE FARGATE_SPOT `
        --region $region `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "Cluster creation failed." }

    aws ecs tag-resource `
        --resource-arn (aws ecs describe-clusters --clusters $clusterName --region $region --query "clusters[0].clusterArn" --output text) `
        --tags key=Name,value=$clusterName key=Project,value=$appName `
        --region $region

    # ================= CREATE ECS SERVICE =================

    Write-Host "Creating ECS service..."

    aws ecs create-service `
        --cluster $clusterName `
        --service-name $serviceName `
        --task-definition $taskDefArn `
        --desired-count 1 `
        --launch-type FARGATE `
        --load-balancers "targetGroupArn=$tgArn,containerName=fastapi-api,containerPort=8000" `
        --network-configuration "awsvpcConfiguration={subnets=[$subnet1a,$subnet1b],securityGroups=[$ecsSg],assignPublicIp=ENABLED}" `
        --region $region `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "Service creation failed." }

    $serviceArn = aws ecs describe-services `
        --cluster $clusterName `
        --services $serviceName `
        --region $region `
        --query "services[0].serviceArn" `
        --output text

    aws ecs tag-resource `
        --resource-arn $serviceArn `
        --tags key=Name,value=$serviceName key=Project,value=$appName `
        --region $region

    aws ecr create-repository `
        --repository-name $repoName `
        --image-tag-mutability MUTABLE `
        --image-scanning-configuration scanOnPush=false `
        --encryption-configuration encryptionType=AES256 `
        --tags Key=Name,Value="$appName-ecr" Key=Project,Value="$appName"

    Write-Host "Before deploying the app, make sure to configure your frontend to point to the API Gateway endpoint: $apiEndpoint"

    Write-Host "And your FastAPI CORS settings to allow requests from: $amplifyUrl"

    Read-Host -Prompt "Press Enter to continue"

    # ================= BUILD FRONTEND =================
    Write-Host "Building frontend..."

    Push-Location $frontendDir
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed." }

    npm run build
    if ($LASTEXITCODE -ne 0) { throw "npm build failed." }
    Pop-Location

    # ================= ZIP DEL FRONTEND =================
    #
    # Con Compress-Archive, que viene en PowerShell. Antes se llamaba a `zip`
    # dentro de WSL: una dependencia que no esta declarada en ninguna parte y
    # cuya ausencia tumbaba el despliegue entero. `dist` ya es salida limpia de
    # Vite, asi que no hay nada que excluir.

    Write-Host "Zipping dist..."

    $zipFullPath = Join-Path $projectPath $frontendZipName
    New-ZipDeCarpeta -Origen $distDir -Destino $zipFullPath

    # ================= UPLOAD ZIP =================
    Write-Host "Uploading ZIP..."

    aws s3 cp $zipFullPath "s3://$bucketName/$frontendZipName"
    if ($LASTEXITCODE -ne 0) { throw "Upload failed." }

    # ================= PRESIGNED URL =================
    $presignedUrl = aws s3 presign "s3://$bucketName/$frontendZipName" --expires-in 3600
    if ($LASTEXITCODE -ne 0) { throw "Presign failed." }

    # ================= DEPLOY =================
    Write-Host "Starting deployment..."

    aws amplify start-deployment `
        --region $region `
        --app-id $appId `
        --branch-name $branchName `
        --source-url $presignedUrl

    if ($LASTEXITCODE -ne 0) { throw "Deployment failed to start." }

    Write-Host "Deployment triggered successfully."

    # ================= CREATE BACKEND ZIP =================

    Write-Host "Creating file $backendZipName..."

    # ================= ZIP DEL BACKEND =================
    #
    # `Compress-Archive` aplana la estructura si se le pasa una lista de
    # archivos, y CodeBuild necesita el arbol intacto para encontrar el
    # buildspec. Por eso se copia primero a una carpeta de paso con robocopy,
    # que si sabe excluir directorios, y se comprime esa carpeta entera.
    #
    # `frontend` queda fuera a proposito: lo publica Amplify, no esta imagen.

    $backendZipPath = Join-Path $projectPath $backendZipName
    if (Test-Path $backendZipPath) { Remove-Item $backendZipPath -Force }

    $staging = Join-Path $env:TEMP "supplyopt-backend-zip"
    if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }

    robocopy $projectPath $staging /E /NFL /NDL /NJH /NJS /NP `
        /XD .venv .git frontend node_modules __pycache__ .pytest_cache .ruff_cache artifacts\mlruns `
        /XF *.pyc *.zip .env | Out-Null

    # Robocopy usa 0-7 para exito y 8 o mas para error. Sin normalizarlo, el
    # siguiente `if ($LASTEXITCODE -ne 0)` del script leeria un exito como fallo.
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

    # ================= CREATE CODEBUILD PROJECT =================
    #
    # Se crea aqui, y no antes, porque el proyecto declara como fuente el objeto
    # de S3: describirlo cuando el zip todavia no esta subido deja el proyecto
    # apuntando a algo inexistente. Ahora el objeto ya esta en el bucket cuando
    # se declara, y start-build ocurre inmediatamente despues.

    Write-Host "Creating CodeBuild project..."

    # Dos cosas que hay que hacer a la vez y por motivos distintos.
    #
    # Una sola conversion a JSON: convertir dos veces envolvia el objeto como
    # cadena y CodeBuild recibia "{\"type\":\"S3\"...}" en vez de un objeto.
    #
    # Y las comillas escapadas: al pasar un argumento a un ejecutable nativo,
    # Windows PowerShell 5.1 se come las comillas dobles, asi que aws recibia
    # {type:S3,location:...} y lo rechazaba por JSON invalido. Es la misma forma
    # que ya usan --artifacts, --environment y --logs-config mas abajo.
    $sourceJson = (@{type = "S3"; location = "${bucketName}/${backendZipName}"} |
        ConvertTo-Json -Compress) -replace '"', '\"'

    aws codebuild create-project `
        --name "$codebuildProjectName" `
        --region $region `
        --source $sourceJson `
        --artifacts '{\"type\":\"NO_ARTIFACTS\"}' `
        --environment '{\"type\":\"LINUX_CONTAINER\",\"image\":\"aws/codebuild/amazonlinux-x86_64-standard:5.0\",\"computeType\":\"BUILD_GENERAL1_SMALL\",\"privilegedMode\":true,\"imagePullCredentialsType\":\"CODEBUILD\"}' `
        --service-role "arn:aws:iam::${accountId}:role/service-role/${codebuildServiceRoleName}" `
        --timeout-in-minutes 15 `
        --queued-timeout-in-minutes 480 `
        --logs-config '{\"cloudWatchLogs\":{\"status\":\"ENABLED\"},\"s3Logs\":{\"status\":\"DISABLED\"}}' `
        --output text

    if ($LASTEXITCODE -ne 0) { throw "CodeBuild project creation failed." }

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
    
} catch {
    # ================= CLEANUP FUNCTION =================
    function Cleanup {
        param (
            [string]$appName,
            [string]$region
        )

        Write-Host "Starting cleanup for app: $appName"

        # ----- 1. Amplify App -----
        try {
            $existingAppId = aws amplify list-apps --region $region --query "apps[?name=='$appName'].appId | [0]" --output text
            if ($existingAppId -and $existingAppId -ne "None") {
                Write-Host "Deleting existing Amplify app..."
                aws amplify delete-app --app-id $existingAppId --region $region --output text

                # Wait until app no longer exists
                while ($true) {
                    Start-Sleep -Seconds 5
                    try {
                        aws amplify get-app --app-id $existingAppId --region $region > $null 2>&1
                        # App still exists, continue waiting
                        Write-Host "Waiting for Amplify app to be deleted..."
                    } catch {
                        # If the app is not found, exit the loop
                        if ($_.Exception.Message -match "NotFoundException") {
                            Write-Host "Amplify app deleted."
                            break
                        } else {
                            Write-Warning "Unexpected error checking Amplify app: $_"
                            break
                        }
                    }
                }
            } else {
                Write-Host "No existing Amplify app found."
            }
        } catch { Write-Warning "Amplify cleanup failed: $_" }

        # ----- 2. S3 Bucket -----
        try {
            aws s3api head-bucket --bucket $bucketName > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Emptying and deleting S3 bucket: $bucketName"
                aws s3 rm "s3://$bucketName" --recursive --region $region
                aws s3api delete-bucket --bucket $bucketName --region $region
            }
        } catch { Write-Warning "S3 cleanup failed: $_" }

        # ----- 3. API Gateway -----
        try {
            $apiId = aws apigatewayv2 get-apis --region $region --query "Items[?Name=='$appName'].ApiId | [0]" --output text
            if ($apiId -and $apiId -ne "None") {
                Write-Host "Deleting API Gateway: $apiId"
                aws apigatewayv2 delete-api --api-id $apiId --region $region
            }
        } catch { Write-Warning "API Gateway cleanup failed: $_" }

        # ----- 4. ECS Service, Cluster, Log Group -----
        if ($logGroupName) {
            try {
                aws logs describe-log-groups --log-group-name-prefix $logGroupName --region $region > $null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Deleting CloudWatch log group: $logGroupName"
                    aws logs delete-log-group --log-group-name $logGroupName --region $region
                }
            } catch { Write-Warning "CloudWatch logs cleanup failed: $_" }
        }

        try {
            aws ecs describe-services --cluster $clusterName --services $serviceName --region $region > $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Deleting ECS service: $serviceName"
                aws ecs delete-service --cluster $clusterName --service $serviceName --force --region $region --output text
            }
        } catch { Write-Warning "ECS service cleanup failed: $_" }

        try {
            aws ecs describe-clusters --clusters $clusterName --region $region > $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Deleting ECS cluster: $clusterName"
                aws ecs delete-cluster --cluster $clusterName --region $region --output text
            }
        } catch { Write-Warning "ECS cluster cleanup failed: $_" }

        Write-Host "Deleting ECR repository: $repoName"

        try {
            aws ecr delete-repository `
                --repository-name $repoName `
                --region $region `
                --force
        }
        catch {
            Write-Warning "ECR repository cleanup failed: $_"
        }

        # ----- 5. IAM Roles -----
        $roles = @($ecsExecutionRoleName, $ecsTaskRoleName, "$codebuildServiceRoleName")
        foreach ($role in $roles) {
            try {
                aws iam get-role --role-name $role --region $region > $null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Deleting IAM role: $role"
                    $policies = aws iam list-attached-role-policies --role-name $role --query "AttachedPolicies[].PolicyArn" --output text --region $region
                    if ($policies -and $policies -ne "None") {
                        $policies = $policies.Split("", [System.StringSplitOptions]::RemoveEmptyEntries)
                    }
                    foreach ($policy in $policies) { aws iam detach-role-policy --role-name $role --policy-arn $policy --region $region }

                    if ( $role -eq "$codebuildServiceRoleName" ) {
                        # Also delete inline policy
                        aws iam delete-role-policy --role-name $role --policy-name "$codebuildProjectName-inline-policy" --region $region
                    }

                    aws iam delete-role --role-name $role --region $region
                    
                }
            } catch { Write-Warning "IAM role cleanup failed for ${role}" }
        }

        Write-Host "Deleting task definition"

        try {
            $taskDefs = aws ecs list-task-definitions `
                --family-prefix $appName `
                --region $region `
                --query "taskDefinitionArns[]" `
                --output text
            foreach ($td in $taskDefs.Split("", [System.StringSplitOptions]::RemoveEmptyEntries)) {
                aws ecs deregister-task-definition `
                    --task-definition $td `
                    --region $region `
                    --output text
            }
        } catch { Write-Warning "Task definition cleanup failed: $_" }

        # ----- 6. ALB and Target Groups -----
        try {
            aws elbv2 describe-load-balancers --names "$appName-alb" --region $region > $null
            if ($LASTEXITCODE -eq 0) {
                $albArn = aws elbv2 describe-load-balancers --names "$appName-alb" --region $region --query "LoadBalancers[0].LoadBalancerArn" --output text
                Write-Host "Deleting listeners for ALB..."
                $listenerArns = aws elbv2 describe-listeners --load-balancer-arn $albArn --region $region --query "Listeners[].ListenerArn" --output text
                foreach ($lArn in $listenerArns) { aws elbv2 delete-listener --listener-arn $lArn --region $region }

                Write-Host "Deleting ALB..."
                aws elbv2 delete-load-balancer --load-balancer-arn $albArn --region $region

                Write-Host "Deleting target groups..."
                $tgArns = aws elbv2 describe-target-groups --names "$appName-tg" --region $region --query "TargetGroups[].TargetGroupArn" --output text
                foreach ($tgArn in $tgArns) { aws elbv2 delete-target-group --target-group-arn $tgArn --region $region }
            }
        } catch { Write-Warning "ALB/Target Group cleanup failed: $_" }

        aws codebuild delete-project `
            --name "$codebuildProjectName" `
            --region $region

        Write-Host "Cleanup completed for app: $appName"
    }

    # ================= CALL CLEANUP =================
    #
    # Se limpia siempre que algo falle: deja la cuenta sin restos a medias, que
    # es lo que permite volver a lanzar desde cero sin choques de nombres.
    #
    # Se imprime antes el error, porque el motivo del fallo se perdia entre la
    # cascada de borrados y sin el no hay forma de saber que corregir.

    # Con $ErrorActionPreference = "Stop", Write-Error es terminante: usado aqui
    # abortaba el propio catch y Cleanup no llegaba a ejecutarse nunca. El aviso
    # va con Write-Host, que no puede interrumpir nada.
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host " EL DESPLIEGUE FALLO" -ForegroundColor Red
    Write-Host "==================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host " $($_.Exception.Message)" -ForegroundColor Red
    Write-Host ""
    Write-Host " Se puede borrar todo lo creado para volver a lanzar desde cero," -ForegroundColor Yellow
    Write-Host " o dejarlo en pie para inspeccionar que quedo a medias." -ForegroundColor Yellow
    Write-Host ""
    Write-Host " Borra: app Amplify, bucket S3, API Gateway, log group, servicio y" -ForegroundColor Yellow
    Write-Host " cluster ECS, repositorio ECR, roles IAM, ALB y proyecto CodeBuild." -ForegroundColor Yellow
    Write-Host ""

    $respuesta = Read-Host " Escribe S para borrar, cualquier otra cosa para dejarlo"

    if ($respuesta -eq 'S' -or $respuesta -eq 's') {
        Write-Host ""
        Write-Host "Limpiando lo creado..." -ForegroundColor Yellow
        Cleanup -appName $appName -region $region
    } else {
        Write-Host ""
        Write-Host "No se ha borrado nada. Recuerda que los recursos que queden" -ForegroundColor Cyan
        Write-Host "provocaran choques de nombres en la siguiente corrida." -ForegroundColor Cyan
    }
}
