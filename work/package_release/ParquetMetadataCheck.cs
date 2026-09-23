using System;
using System.IO;
using ParquetSharp;

internal static class ParquetMetadataCheck
{
    public static int Main(string[] args)
    {
        if (args.Length == 0)
        {
            Console.Error.WriteLine("Usage: ParquetMetadataCheck <file.parquet> [...]");
            return 2;
        }

        try
        {
            foreach (var path in args)
            {
                using (var reader = new ParquetFileReader(path))
                {
                    var metadata = reader.FileMetaData;
                    if (metadata.NumRowGroups > 0)
                    {
                        using (var rowGroup = reader.RowGroup(0))
                        using (var column = rowGroup.Column(0))
                        {
                            // Opening the first physical column verifies that the row-group footer is readable.
                        }
                    }
                    Console.WriteLine(path + "\t" + metadata.NumRows + "\t" + metadata.NumColumns + "\t" + metadata.NumRowGroups);
                }
            }
            return 0;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.ToString());
            return 1;
        }
    }
}
