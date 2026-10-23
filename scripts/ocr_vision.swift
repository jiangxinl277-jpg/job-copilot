// macOS Vision OCR helper: prints recognized text lines for one image.
// Build: swiftc -O scripts/ocr_vision.swift -o lib/ocr_vision
// Usage: ./lib/ocr_vision <image path> [zh-Hans en-US]
import Foundation
import AppKit
import Vision

let args = CommandLine.arguments
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: ocr_vision <image> [lang...]\n".data(using: .utf8)!)
    exit(2)
}
let path = args[1]
let langs = args.count > 2 ? Array(args[2...]) : ["zh-Hans", "en-US"]

guard let image = NSImage(contentsOfFile: path),
      let tiff = image.tiffRepresentation,
      let rep = NSBitmapImageRep(data: tiff),
      let cg = rep.cgImage else {
    FileHandle.standardError.write("cannot load image: \(path)\n".data(using: .utf8)!)
    exit(3)
}

let request = VNRecognizeTextRequest { req, err in
    if let err = err {
        FileHandle.standardError.write("vision error: \(err)\n".data(using: .utf8)!)
        exit(4)
    }
    guard let observations = req.results as? [VNRecognizedTextObservation] else { return }
    // 按上到下、左到右排序，尽量还原阅读顺序
    let sorted = observations.sorted { a, b in
        if abs(a.boundingBox.midY - b.boundingBox.midY) > 0.01 {
            return a.boundingBox.midY > b.boundingBox.midY
        }
        return a.boundingBox.minX < b.boundingBox.minX
    }
    for obs in sorted {
        if let candidate = obs.topCandidates(1).first {
            print(candidate.string)
        }
    }
}

request.recognitionLevel = .accurate
request.recognitionLanguages = langs
request.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write("perform failed: \(error)\n".data(using: .utf8)!)
    exit(5)
}
