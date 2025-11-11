param(
    [string]$OutputPath = "out/gpw_liquidity_program_joinings.xlsx",
    [string]$Query,
    [string]$CategoryIds = "2,8,9,11,43,44"
)

if (-not $PSBoundParameters.ContainsKey('Query') -or -not $Query) {
    $Query = "Programu Wspierania P" + [char]0x0142 + "ynno" + [char]0x015b + "ci"
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Web
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$DefaultHeaders = @{
    "User-Agent"      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    "Accept"          = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    "Accept-Language" = "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7"
}

function Invoke-GpwRequest {
    param(
        [string]$Uri,
        [string]$Method = "GET",
        $Body = $null,
        [int]$MaxAttempts = 10
    )

    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        try {
            $parameters = @{
                Uri             = $Uri
                Method          = $Method
                Headers         = $DefaultHeaders
                UseBasicParsing = $true
            }
            if ($Method -eq "POST" -and $Body) {
                $parameters.Body = $Body
            }
            return Invoke-WebRequest @parameters
        } catch {
            if ($attempt -ge $MaxAttempts) {
                throw
            }
            $sleepSeconds = 2 * $attempt
            $statusCode = $null
            if ($_.Exception.Response -and $_.Exception.Response -is [System.Net.HttpWebResponse]) {
                $statusCode = [int]$_.Exception.Response.StatusCode
            }
            if ($statusCode -eq 403) {
                $sleepSeconds = [Math]::Min(120, 15 * $attempt)
            }
            $jitter = Get-Random -Minimum 0 -Maximum 1
            Start-Sleep -Seconds ($sleepSeconds + $jitter)
        }
    }
}

function Remove-Diacritics {
    param([string]$Text)
    if (-not $Text) { return "" }
    $normalized = $Text.Normalize([Text.NormalizationForm]::FormD)
    $builder = New-Object System.Text.StringBuilder
    foreach ($char in $normalized.ToCharArray()) {
        if ([System.Globalization.CharUnicodeInfo]::GetUnicodeCategory($char) -ne [System.Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$builder.Append($char)
        }
    }
    return $builder.ToString()
}

function Get-ExcelColumnName {
    param([int]$Index)
    $result = ""
    while ($Index -gt 0) {
        $Index -= 1
        $result = [char](65 + ($Index % 26)) + $result
        $Index = [math]::Floor($Index / 26)
    }
    return $result
}

function Escape-Xml {
    param([string]$Value)
    if ($null -eq $Value) {
        return ""
    }
    return [System.Security.SecurityElement]::Escape($Value)
}

function Add-ZipTextEntry {
    param(
        [System.IO.Compression.ZipArchive]$Archive,
        [string]$EntryName,
        [string]$Content
    )
    $entry = $Archive.CreateEntry($EntryName)
    $writer = New-Object System.IO.StreamWriter($entry.Open(), [System.Text.Encoding]::UTF8)
    $writer.NewLine = "`n"
    $writer.Write($Content)
    $writer.Dispose()
}

function Build-SheetXml {
    param([System.Collections.Generic.List[object]]$Rows)

    $headers = @(
        "Company",
        "Announcement Date",
        "Effective Date",
        "Announcement Title",
        "Detail URL",
        "cmn_id"
    )

    $sheetBuilder = New-Object System.Text.StringBuilder
    [void]$sheetBuilder.AppendLine('<?xml version="1.0" encoding="UTF-8"?>')
    [void]$sheetBuilder.Append('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ')
    [void]$sheetBuilder.AppendLine('xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">')
    [void]$sheetBuilder.AppendLine('<sheetData>')

    $rowIndex = 1
    [void]$sheetBuilder.AppendLine("<row r=""$rowIndex"">")
    for ($i = 0; $i -lt $headers.Count; $i++) {
        $column = Get-ExcelColumnName($i + 1)
        $value = Escape-Xml($headers[$i])
        [void]$sheetBuilder.AppendLine("<c r=""$column$rowIndex"" t=""str""><v>$value</v></c>")
    }
    [void]$sheetBuilder.AppendLine("</row>")

    foreach ($row in $Rows) {
        $rowIndex += 1
        [void]$sheetBuilder.AppendLine("<row r=""$rowIndex"">")
        $values = @(
            $row.Company,
            $row.AnnouncementDate.ToString("yyyy-MM-dd"),
            $row.EffectiveDate.ToString("yyyy-MM-dd"),
            $row.Title,
            $row.DetailUrl,
            $row.CmnId
        )
        for ($i = 0; $i -lt $values.Count; $i++) {
            $column = Get-ExcelColumnName($i + 1)
            $encoded = Escape-Xml($values[$i])
            [void]$sheetBuilder.AppendLine("<c r=""$column$rowIndex"" t=""str""><v>$encoded</v></c>")
        }
        [void]$sheetBuilder.AppendLine("</row>")
    }

    [void]$sheetBuilder.AppendLine("</sheetData>")
    [void]$sheetBuilder.AppendLine("</worksheet>")

    return $sheetBuilder.ToString()
}

$monthLookup = @{
    "stycznia"    = 1
    "lutego"      = 2
    "marca"       = 3
    "kwietnia"    = 4
    "maja"        = 5
    "czerwca"     = 6
    "lipca"       = 7
    "sierpnia"    = 8
    "wrzesnia"    = 9
    "pazdziernika"= 10
    "listopada"   = 11
    "grudnia"     = 12
}

$baseUri = "https://www.gpw.pl"
$listEndpoint = "$baseUri/ajaxindex.php"
$pageLimit = 10

$announcements = New-Object System.Collections.Generic.List[object]
$detailCache = @{}
$seenKeys = New-Object System.Collections.Generic.HashSet[string]

$offset = 0
while ($true) {
    $body = @{
        action               = "CMNews"
        start                = "ajaxList"
        page_iterator_active = "true"
        page                 = "komunikaty-i-uchwaly-gpw"
        target               = "main_01"
        limit                = "$pageLimit"
        offset               = "$offset"
    }
    if ($Query) {
        $body["query"] = $Query
    }
    if ($CategoryIds) {
        $body["cmng_id"] = $CategoryIds
    }

    $pageHtml = (Invoke-GpwRequest -Uri $listEndpoint -Method "POST" -Body $body).Content
    $regexOptions = [System.Text.RegularExpressions.RegexOptions]::Singleline -bor [System.Text.RegularExpressions.RegexOptions]::Multiline
    $liRegex = [regex]::new('<li>.*?<span class="date">.*?</li>', $regexOptions)
    $liMatches = $liRegex.Matches($pageHtml)
    Start-Sleep -Milliseconds 500

    if ($liMatches.Count -eq 0) {
        break
    }

    foreach ($match in $liMatches) {
        $liContent = $match.Value
        $dateMatch = [regex]::Match($liContent, '\|\s*(\d{2}-\d{2}-\d{4})</span>')
        if (-not $dateMatch.Success) { continue }
        $publicationDate = [datetime]::ParseExact(
            $dateMatch.Groups[1].Value,
            "dd-MM-yyyy",
            [System.Globalization.CultureInfo]::InvariantCulture
        )

        $linkMatch = [regex]::Match($liContent, '<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
        if (-not $linkMatch.Success) { continue }

        $relativeHref = [System.Net.WebUtility]::HtmlDecode($linkMatch.Groups[1].Value)
        $detailUrl = if ($relativeHref.StartsWith("http")) { $relativeHref } else { "$baseUri$relativeHref" }

        $titleHtml = $linkMatch.Groups[2].Value
        $titleText = [System.Net.WebUtility]::HtmlDecode(($titleHtml -replace '<[^>]+>', '')).Trim()

        $companies = @()
        $effectiveDate = $publicationDate
        $cachedDetail = $null
        if ($detailCache.ContainsKey($detailUrl)) {
            $cachedDetail = $detailCache[$detailUrl]
            $companies = @($cachedDetail.Companies)
            if ($cachedDetail.EffectiveDate) {
                $effectiveDate = $cachedDetail.EffectiveDate
            }
        } else {
            $detailHtml = (Invoke-GpwRequest -Uri $detailUrl).Content
            Start-Sleep -Milliseconds 1000
            $paragraphRegex = [regex]::new('<p[^>]*>.*?</p>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
            $paragraphMatches = $paragraphRegex.Matches($detailHtml)

            $joinIndex = -1
            $joinParagraphText = $null
            for ($i = 0; $i -lt $paragraphMatches.Count; $i++) {
                $paragraphHtml = $paragraphMatches[$i].Value
                $plain = [System.Net.WebUtility]::HtmlDecode(($paragraphHtml -replace '<[^>]+>', ' '))
                $plain = ($plain -replace '\s+', ' ').Trim()
                if (-not $plain) { continue }
                $normalized = (Remove-Diacritics $plain).ToLower()
                if ($normalized -like '*programu wspierania*' -and $normalized -like '*przyst*') {
                    $joinIndex = $i
                    $joinParagraphText = $plain
                    break
                }
            }

            if ($joinIndex -lt 0) {
                $detailCache[$detailUrl] = [pscustomobject]@{ EffectiveDate = $null; Companies = @() }
                continue
            }

            $normalizedJoin = (Remove-Diacritics $joinParagraphText).ToLower()
            $effectiveMatch = [regex]::Match($normalizedJoin, '(?:z\s+dniem|w\s+dniu|od\s+dnia)\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})')
            if ($effectiveMatch.Success) {
                $day = [int]$effectiveMatch.Groups[1].Value
                $monthName = $effectiveMatch.Groups[2].Value
                if ($monthLookup.ContainsKey($monthName)) {
                    $month = $monthLookup[$monthName]
                    $effectiveDate = [datetime]::new([int]$effectiveMatch.Groups[3].Value, $month, $day)
                }
            }

            $paragraphHtml = $paragraphMatches[$joinIndex].Value
            $start = $detailHtml.IndexOf($paragraphHtml)
            if ($start -ge 0) {
                $afterParagraph = $detailHtml.Substring($start + $paragraphHtml.Length)
                $trimmedAfter = $afterParagraph.TrimStart()
                if ($trimmedAfter.StartsWith("<ul", [System.StringComparison]::OrdinalIgnoreCase)) {
                    $ulMatch = [regex]::Match($trimmedAfter, '<ul[^>]*>.*?</ul>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
                    if ($ulMatch.Success) {
                        $liCompanyMatches = [regex]::Matches($ulMatch.Value, '<li[^>]*>(.*?)</li>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
                        foreach ($liCompany in $liCompanyMatches) {
                            $companyPlain = [System.Net.WebUtility]::HtmlDecode(($liCompany.Groups[1].Value -replace '<[^>]+>', ' '))
                            $companyPlain = ($companyPlain -replace '\s+', ' ').Trim().Trim(",; ")
                            if ($companyPlain -and $companyPlain -match '[A-Z]') {
                                $companies += $companyPlain
                            }
                        }
                    }
                }
            }

            if ($companies.Count -eq 0) {
                $colonIndex = $joinParagraphText.IndexOf(':')
                if ($colonIndex -ge 0 -and $normalizedJoin -like '*spolk*:*') {
                    $listPart = $joinParagraphText.Substring($colonIndex + 1)
                    $nameMatches = [regex]::Matches($listPart, '(?:^|[,\s])([A-Za-z0-9][A-Za-z0-9\?\s\.\-&]*?(?:S\.A\.?|S\.E|SE|INC\.?))')
                    foreach ($nameMatch in $nameMatches) {
                        $candidate = $nameMatch.Groups[1].Value.Trim()
                        $candidate = ($candidate -replace '^(?:oraz|i)\s+', '').Trim(",; ")
                        if ($candidate) {
                            $companies += $candidate
                        }
                    }
                }
            }

            if ($companies.Count -eq 0) {
                $singleMatch = [regex]::Match($joinParagraphText, 'sp\S*ka\s+([A-Za-z0-9][A-Za-z0-9\s\.\-&]*?)(?:[,.;]|$)')
                if ($singleMatch.Success) {
                    $candidate = $singleMatch.Groups[1].Value.Trim().Trim(",; ")
                    if ($candidate) {
                        $companies += $candidate
                    }
                }
            }

            if ($companies.Count -eq 0) {
                for ($j = $joinIndex + 1; $j -lt $paragraphMatches.Count; $j++) {
                    $nextParaHtml = $paragraphMatches[$j].Value
                    $strongMatch = [regex]::Match($nextParaHtml, '<strong>(.*?)</strong>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
                    if ($strongMatch.Success) {
                        $candidate = [System.Net.WebUtility]::HtmlDecode(($strongMatch.Groups[1].Value -replace '<[^>]+>', ' '))
                        $candidate = ($candidate -replace '\s+', ' ').Trim().Trim(",; ")
                        if ($candidate) {
                            $companies += $candidate
                            break
                        }
                    }
                    $text = [System.Net.WebUtility]::HtmlDecode(($nextParaHtml -replace '<[^>]+>', ' '))
                    if ($text.Trim()) {
                        break
                    }
                }
            }

            if ($companies.Count -eq 0) {
                $fallback = $titleText.Split('(')[0].Trim()
                if ($fallback) {
                    $normalizedFallback = (Remove-Diacritics $fallback).ToLower()
                    if ($normalizedFallback -notin @("komunikat", "program wspierania p?ynnosci", "pwp / snp", "snp / pwp", "uchwala")) {
                        $companies += $fallback
                    }
                }
            }

            $companies = @(
                $companies |
                Where-Object {
                    if (-not $_) { return $false }
                    $name = $_.Trim()
                    if (-not $name) { return $false }
                    $normalizedName = (Remove-Diacritics $name).ToLower()
                    if ($normalizedName -like '*gie?da papierow wartosciowych*') { return $false }
                    if ($normalizedName -like '*w warszawie s.a.*') { return $false }
                    if ($normalizedName -like 'program wspierania*') { return $false }
                    if ($normalizedName -eq 'komunikat') { return $false }
                    if ($normalizedName -match '^[a-z]$') { return $false }
                    return $true
                } |
                Select-Object -Unique
            )

            if ($companies.Count -eq 0) {
                $detailCache[$detailUrl] = [pscustomobject]@{ EffectiveDate = $null; Companies = @() }
                continue
            }

            $detailCache[$detailUrl] = [pscustomobject]@{
                EffectiveDate = $effectiveDate
                Companies     = @($companies)
            }
        }

        if ($companies.Count -eq 0) { continue }

        $cmnId = $null
        try {
            $uri = [Uri]$detailUrl
            if ($uri.Query) {
                $parsed = [System.Web.HttpUtility]::ParseQueryString($uri.Query)
                $cmnId = $parsed["cmn_id"]
            }
        } catch {
        }

        foreach ($company in $companies) {
            $dedupeKey = "{0}|{1}|{2}" -f $company, $effectiveDate.ToString("yyyy-MM-dd"), $detailUrl
            if (-not $seenKeys.Add($dedupeKey)) {
                continue
            }
            $announcements.Add([pscustomobject]@{
                Company          = $company
                AnnouncementDate = $publicationDate
                EffectiveDate    = $effectiveDate
                Title            = $titleText
                DetailUrl        = $detailUrl
                CmnId            = $cmnId
            })
        }
    }

    if ($liMatches.Count -lt $pageLimit) {
        break
    }

    $offset += $pageLimit
}

if ($announcements.Count -eq 0) {
    throw "No liquidity programme join announcements found."
}

$announcements.Sort({
    param($a, $b)
    $dateComparison = $a.AnnouncementDate.CompareTo($b.AnnouncementDate)
    if ($dateComparison -ne 0) { return $dateComparison }
    return [string]::Compare($a.Company, $b.Company, $true)
})

$sheetXml = Build-SheetXml $announcements
$now = [datetime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")

$contentTypesXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
'@

$relsXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
'@

$workbookRelsXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>
'@

$workbookXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <fileVersion appName="xl"/>
  <sheets>
    <sheet name="LiquidityJoins" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>
'@

$stylesXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1">
    <font>
      <sz val="11"/>
      <color theme="1"/>
      <name val="Calibri"/>
      <family val="2"/>
    </font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border>
      <left/><right/><top/><bottom/><diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
  <cellStyles count="1">
    <cellStyle name="Normal" xfId="0" builtinId="0"/>
  </cellStyles>
</styleSheet>
'@

$coreXml = @"
<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:creator>Generated by PowerShell</dc:creator>
  <cp:lastModifiedBy>Generated by PowerShell</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">$now</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">$now</dcterms:modified>
  <dc:title>GPW Liquidity Programme Joinings</dc:title>
</cp:coreProperties>
"@

$appXml = @'
<?xml version="1.0" encoding="UTF-8"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Excel</Application>
  <DocSecurity>0</DocSecurity>
  <ScaleCrop>false</ScaleCrop>
  <HeadingPairs>
    <vt:vector size="2" baseType="variant">
      <vt:variant>
        <vt:lpstr>Worksheets</vt:lpstr>
      </vt:variant>
      <vt:variant>
        <vt:i4>1</vt:i4>
      </vt:variant>
    </vt:vector>
  </HeadingPairs>
  <TitlesOfParts>
    <vt:vector size="1" baseType="lpstr">
      <vt:lpstr>LiquidityJoins</vt:lpstr>
    </vt:vector>
  </TitlesOfParts>
  <Company></Company>
  <LinksUpToDate>false</LinksUpToDate>
  <SharedDoc>false</SharedDoc>
  <HyperlinksChanged>false</HyperlinksChanged>
  <AppVersion>16.0300</AppVersion>
</Properties>
'@

$outputFile = [System.IO.Path]::GetFullPath($OutputPath)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputFile)) | Out-Null
if (Test-Path $outputFile) {
    Remove-Item $outputFile
}

$fileStream = [System.IO.File]::Open($outputFile, [System.IO.FileMode]::CreateNew)
try {
    $zip = New-Object System.IO.Compression.ZipArchive($fileStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
    Add-ZipTextEntry -Archive $zip -EntryName "[Content_Types].xml" -Content $contentTypesXml
    Add-ZipTextEntry -Archive $zip -EntryName "_rels/.rels" -Content $relsXml
    Add-ZipTextEntry -Archive $zip -EntryName "docProps/core.xml" -Content $coreXml
    Add-ZipTextEntry -Archive $zip -EntryName "docProps/app.xml" -Content $appXml
    Add-ZipTextEntry -Archive $zip -EntryName "xl/workbook.xml" -Content $workbookXml
    Add-ZipTextEntry -Archive $zip -EntryName "xl/_rels/workbook.xml.rels" -Content $workbookRelsXml
    Add-ZipTextEntry -Archive $zip -EntryName "xl/styles.xml" -Content $stylesXml
    Add-ZipTextEntry -Archive $zip -EntryName "xl/worksheets/sheet1.xml" -Content $sheetXml
    $zip.Dispose()
} finally {
    $fileStream.Dispose()
}

Write-Host "Saved $($announcements.Count) records to $outputFile"
