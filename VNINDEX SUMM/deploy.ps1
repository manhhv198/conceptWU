# Deploy Script for Cloud Run Job
# Usage: .\deploy.ps1 -ProjectId "YOUR_PROJECT_ID" -Bucket "YOUR_GCS_BUCKET"

param (
    [string]$ProjectId,
    [string]$Bucket,
    [string]$Region = "asia-southeast1",
    [string]$JobName = "vnindex-analyzer-job"
)

if (-not $ProjectId) {
    Write-Host "Please provide a Project ID using -ProjectId"
    Write-Host "Example: .\deploy.ps1 -ProjectId my-gcp-project -Bucket my-bucket"
    exit 1
}

if (-not $Bucket) {
    Write-Host "Please provide a GCS Bucket name using -Bucket"
    exit 1
}

Write-Host "Setting project to $ProjectId..."
gcloud config set project $ProjectId


Write-Host "Enabling necessary APIs (if not enabled)..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

$RepoName = "vnindex-repo"
$RepoRegion = $Region

Write-Host "Creating Artifact Registry Repository '$RepoName' in $RepoRegion (if not exists)..."
# Try to create, suppress error if it exists
gcloud artifacts repositories create $RepoName `
    --repository-format=docker `
    --location=$RepoRegion `
    --description="Repository for VNIndex Analyzer" `
    2>$null

Write-Host "Submitting build to Cloud Build..."
# Use Artifact Registry path
$ImageName = "$RepoRegion-docker.pkg.dev/$ProjectId/$RepoName/$JobName"
gcloud builds submit --tag $ImageName .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Creating/Updating Cloud Run Job..."
# Note: We mount /tmp implicitly.
# We pass env vars for GCS_BUCKET_NAME
# 2 CPU, 1GB RAM is usually enough for these scripts (Playwright might need more RAM)
gcloud run jobs deploy $JobName `
    --image $ImageName `
    --region $Region `
    --set-env-vars GCS_BUCKET_NAME=$Bucket `
    --memory 2Gi `
    --cpu 1 `
    --task-timeout 3600 `
    --max-retries 0


if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed!" -ForegroundColor Red
    exit 1
}

Write-Host "Deployment Successful!" -ForegroundColor Green
Write-Host "You can run the job manually with:"
Write-Host "gcloud run jobs execute $JobName --region $Region"
