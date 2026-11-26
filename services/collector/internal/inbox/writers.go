// Package inbox (writers) 负责把清洗结果落成规范化 NDJSON 中间文件与证据。
package inbox

import (
	"path/filepath"
	"strings"
	"time"

	"cbr-maw/services/collector/internal/evidence"
	"cbr-maw/services/collector/internal/output"
	"cbr-maw/services/collector/internal/parse"
)

// writeObservations 把一组观测行写成 NDJSON 并生成文件级证据。
func writeObservations(memberName, hint string, group observationGroup, dropped int, fileBytes []byte, opts Options, batchID string) (Accepted, error) {
	fileHash := evidence.SHA256Hex(fileBytes)
	evidenceID := evidence.EvidenceID("inbox.ingest", "1.0.0", evidence.SHA256String(batchID+"|"+memberName+"|"+group.SeriesID))
	for i := range group.Rows {
		group.Rows[i].EvidenceID = evidenceID
	}
	filename := group.SeriesID + ".ndjson"
	records := make([]any, len(group.Rows))
	for i, row := range group.Rows {
		records[i] = row
	}
	written, err := output.WriteNDJSON(opts.IntermediateDir, filename, records)
	if err != nil {
		return Accepted{}, err
	}
	sourceID := opts.DeclaredSource
	declared := sourceID
	var declaredPtr *string
	if declared != "" {
		declaredPtr = &declared
	}
	// 契约要求 source_id 必填（非 null）：未声明来源时用文件级稳定标识，
	// 而不是留空——留空会让下游无法溯源到具体文件。
	effectiveSourceID := sourceID
	if effectiveSourceID == "" {
		effectiveSourceID = "file:" + filepath.Base(memberName)
	}
	return Accepted{
		File:            filepath.Base(memberName),
		SeriesID:        group.SeriesID,
		Rows:            len(group.Rows),
		ReleaseTimeRule: group.ReleaseRule,
		MappingBasis:    group.MappingBasis,
		Evidence: &evidence.FileEvidence{
			EvidenceID:     evidenceID,
			SourceID:       &effectiveSourceID,
			DeclaredSource: declaredPtr,
			Rows:           len(group.Rows),
			DroppedRows:    dropped,
			Hash:           fileHash,
			File:           filepath.Base(memberName),
			FilePath:       memberName,
			ReadAt:         opts.Now.Format(time.RFC3339),
		},
		writtenPath: written,
	}, nil
}

// writeDocuments 把文档行写成 NDJSON 并生成文件级证据。
func writeDocuments(memberName, hint string, docs []parse.Document, fileBytes []byte, opts Options, batchID string) (Accepted, error) {
	fileHash := evidence.SHA256Hex(fileBytes)
	evidenceID := evidence.EvidenceID("inbox.ingest", "1.0.0", evidence.SHA256String(batchID+"|"+memberName+"|documents"))
	for i := range docs {
		docs[i].EvidenceID = evidenceID
	}
	records := make([]any, len(docs))
	for i, doc := range docs {
		records[i] = doc
	}
	filename := hint + ".documents.ndjson"
	written, err := output.WriteNDJSON(opts.IntermediateDir, filename, records)
	if err != nil {
		return Accepted{}, err
	}
	declared := opts.DeclaredSource
	var declaredPtr *string
	if declared != "" {
		declaredPtr = &declared
	}
	seriesID := "documents." + cleanSafe(hint)
	effectiveSourceID2 := declared
	if effectiveSourceID2 == "" {
		effectiveSourceID2 = "file:" + filepath.Base(memberName)
	}
	return Accepted{
		File:            filepath.Base(memberName),
		SeriesID:        seriesID,
		Rows:            len(docs),
		ReleaseTimeRule: "publish_time 取自发布时间列；缺失时用处理时刻",
		Evidence: &evidence.FileEvidence{
			EvidenceID:     evidenceID,
			SourceID:       &effectiveSourceID2,
			DeclaredSource: declaredPtr,
			Rows:           len(docs),
			DroppedRows:    0,
			Hash:           fileHash,
			File:           filepath.Base(memberName),
			FilePath:       memberName,
			ReadAt:         opts.Now.Format(time.RFC3339),
		},
		writtenPath: written,
	}, nil
}

func cleanSafe(s string) string {
	out := strings.TrimSpace(s)
	if out == "" {
		return "inbox"
	}
	return out
}
