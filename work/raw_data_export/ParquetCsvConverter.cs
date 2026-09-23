using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using Microsoft.VisualBasic.FileIO;
using ParquetSharp;

namespace RawDataExport
{
    internal sealed class FieldDefinition
    {
        public string Name;
        public string Type;
    }

    internal static class ParquetCsvConverter
    {
        private const int RowGroupSize = 10000;

        private static FieldDefinition[] ReadSchema(string path)
        {
            var fields = new List<FieldDefinition>();
            foreach (var line in File.ReadAllLines(path))
            {
                if (String.IsNullOrWhiteSpace(line)) continue;
                var parts = line.Split('\t');
                if (parts.Length != 2) throw new InvalidDataException("Invalid schema line: " + line);
                fields.Add(new FieldDefinition { Name = parts[0], Type = parts[1] });
            }
            return fields.ToArray();
        }

        private static Column CreateColumn(FieldDefinition field)
        {
            switch (field.Type)
            {
                case "int64": return new Column<long?>(field.Name);
                case "double": return new Column<double?>(field.Name);
                case "bool": return new Column<bool?>(field.Name);
                case "string": return new Column<string>(field.Name);
                default: throw new InvalidDataException("Unsupported type: " + field.Type);
            }
        }

        private static TextFieldParser OpenParser(string path)
        {
            Stream stream = File.OpenRead(path);
            if (path.EndsWith(".gz", StringComparison.OrdinalIgnoreCase))
            {
                stream = new GZipStream(stream, CompressionMode.Decompress);
            }
            var parser = new TextFieldParser(stream);
            parser.TextFieldType = FieldType.Delimited;
            parser.SetDelimiters(",");
            parser.HasFieldsEnclosedInQuotes = true;
            parser.TrimWhiteSpace = false;
            return parser;
        }

        private static void ValidateHeader(string[] header, FieldDefinition[] schema)
        {
            if (header == null || header.Length != schema.Length)
                throw new InvalidDataException("CSV/schema column count mismatch.");
            for (var i = 0; i < header.Length; i++)
            {
                if (!String.Equals(header[i], schema[i].Name, StringComparison.Ordinal))
                    throw new InvalidDataException("CSV/schema header mismatch at column " + (i + 1));
            }
        }

        private static void WriteColumn(RowGroupWriter rowGroup, FieldDefinition field, List<string> values)
        {
            using (var physical = rowGroup.NextColumn())
            {
                switch (field.Type)
                {
                    case "int64":
                        var integers = new long?[values.Count];
                        for (var i = 0; i < values.Count; i++)
                            integers[i] = String.IsNullOrEmpty(values[i]) ? (long?)null : Int64.Parse(values[i], CultureInfo.InvariantCulture);
                        using (var logical = physical.LogicalWriter<long?>()) logical.WriteBatch(integers);
                        break;
                    case "double":
                        var doubles = new double?[values.Count];
                        for (var i = 0; i < values.Count; i++)
                            doubles[i] = String.IsNullOrEmpty(values[i]) ? (double?)null : Double.Parse(values[i], CultureInfo.InvariantCulture);
                        using (var logical = physical.LogicalWriter<double?>()) logical.WriteBatch(doubles);
                        break;
                    case "bool":
                        var booleans = new bool?[values.Count];
                        for (var i = 0; i < values.Count; i++)
                        {
                            var value = values[i];
                            booleans[i] = String.IsNullOrEmpty(value) ? (bool?)null : value == "1" || value.Equals("true", StringComparison.OrdinalIgnoreCase);
                        }
                        using (var logical = physical.LogicalWriter<bool?>()) logical.WriteBatch(booleans);
                        break;
                    case "string":
                        var strings = new string[values.Count];
                        for (var i = 0; i < values.Count; i++) strings[i] = String.IsNullOrEmpty(values[i]) ? null : values[i];
                        using (var logical = physical.LogicalWriter<string>()) logical.WriteBatch(strings);
                        break;
                    default:
                        throw new InvalidDataException("Unsupported type: " + field.Type);
                }
            }
        }

        private static long Convert(string csvPath, string schemaPath, string parquetPath)
        {
            var schema = ReadSchema(schemaPath);
            var columns = new Column[schema.Length];
            for (var i = 0; i < schema.Length; i++) columns[i] = CreateColumn(schema[i]);
            var totalRows = 0L;
            using (var parser = OpenParser(csvPath))
            using (var writer = new ParquetFileWriter(parquetPath, columns, Compression.Snappy))
            {
                ValidateHeader(parser.ReadFields(), schema);
                while (!parser.EndOfData)
                {
                    var buffers = new List<string>[schema.Length];
                    for (var i = 0; i < buffers.Length; i++) buffers[i] = new List<string>(RowGroupSize);
                    var rows = 0;
                    while (rows < RowGroupSize && !parser.EndOfData)
                    {
                        var fields = parser.ReadFields();
                        if (fields == null) continue;
                        if (fields.Length != schema.Length)
                            throw new InvalidDataException("CSV row has " + fields.Length + " columns; expected " + schema.Length + ".");
                        for (var i = 0; i < fields.Length; i++) buffers[i].Add(fields[i]);
                        rows++;
                    }
                    if (rows == 0) break;
                    using (var rowGroup = writer.AppendRowGroup())
                    {
                        for (var i = 0; i < schema.Length; i++) WriteColumn(rowGroup, schema[i], buffers[i]);
                    }
                    totalRows += rows;
                }
            }
            using (var reader = new ParquetFileReader(parquetPath))
            {
                var metadata = reader.FileMetaData;
                if (metadata.NumRows != totalRows || metadata.NumColumns != schema.Length)
                    throw new InvalidDataException("Parquet metadata parity failure.");
            }
            return totalRows;
        }

        public static int Main(string[] args)
        {
            if (args.Length != 3)
            {
                Console.Error.WriteLine("Usage: ParquetCsvConverter <csv[.gz]> <schema.tsv> <output.parquet>");
                return 2;
            }
            try
            {
                var rows = Convert(args[0], args[1], args[2]);
                Console.WriteLine("PARQUET_PASS rows=" + rows + " path=" + args[2]);
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine(ex.ToString());
                return 1;
            }
        }
    }
}
