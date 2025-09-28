param (
    [string]$BackupFile = "C:\Users\valer\source\repos\VMAzure\core_api\db_cluster-14-09-2025@23-47-58.backup",
    [string]$TableName = "az_image",
    [string]$ConnString = "postgresql://postgres.vqfloobaovtdtcuflqeu:Azuremilano.2025@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
    [switch]$ForceDrop
)

Write-Host "Estrazione tabella $TableName da $BackupFile..."

$schemaOut = "$TableName`_schema.sql"
$dataOut   = "$TableName`_data.sql"

$inSchemaBlock = $false
$inCopyBlock   = $false
$schemaLines   = @()
$dataLines     = @()

Get-Content $BackupFile | ForEach-Object {
    $line = $_

    # --- Schema block ---
    if ($line -match "-- Name: $TableName") {
        $inSchemaBlock = $true
    }
    elseif ($inSchemaBlock -and $line -match "^-- Name:") {
        $inSchemaBlock = $false
    }

    if ($inSchemaBlock) {
        $schemaLines += $line
    }

    # --- Data block (INSERT o COPY)
    if ($line -match "^INSERT INTO public.${TableName}") {
        $dataLines += $line
    }
    elseif ($line -match "^COPY public.${TableName}") {
        $dataLines += $line
        $inCopyBlock = $true
    }
    elseif ($inCopyBlock) {
        $dataLines += $line
        if ($line -eq "\.") {
            $inCopyBlock = $false
        }
    }
}

# Salvataggio file
if ($schemaLines.Count -gt 0) {
    $schemaLines | Set-Content $schemaOut
    Write-Host "Schema salvato in $schemaOut"
} else {
    Write-Host "⚠ Schema non trovato!"
}

if ($dataLines.Count -gt 0) {
    $dataLines | Set-Content $dataOut
    Write-Host "Dati salvati in $dataOut ($($dataLines.Count) righe trovate)"
} else {
    Write-Host "⚠ Nessun dato trovato!"
}

# Import diretto in Supabase
if ($ForceDrop) {
    Write-Host "DROP tabella esistente..."
    & psql $ConnString -c "DROP TABLE IF EXISTS public.${TableName} CASCADE;"
}

if (Test-Path $schemaOut) {
    Write-Host "Ricreo tabella $TableName..."
    & psql $ConnString -f $schemaOut
}
if (Test-Path $dataOut) {
    Write-Host "Carico dati..."
    & psql $ConnString -f $dataOut
}

Write-Host "✅ Tabella $TableName ripristinata."
