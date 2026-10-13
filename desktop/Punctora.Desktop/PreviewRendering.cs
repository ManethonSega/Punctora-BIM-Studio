using System.Diagnostics;
using System.Numerics;

namespace Punctora.Desktop;

public enum PreviewQuality { Adaptive, Low, Medium, High }

public sealed class PreviewDensity
{
    public const double RestoreDelayMs = 150;
    public static double Now => Stopwatch.GetTimestamp() * 1000d / Stopwatch.Frequency;
    public PreviewQuality Quality { get; set; } = PreviewQuality.Adaptive;
    public bool Moving { get; private set; }
    public int AdaptiveMovingPoints { get; private set; } = 100_000;
    public double LastInputMs { get; private set; }
    public double RestoreMs { get; private set; }
    public double RestoreRenderedMs { get; private set; }
    bool awaitingRestore;
    public void Input(double now) { LastInputMs = now; Moving = true; awaitingRestore = true; }
    public void Rendered(double now)
    { if (!Moving && awaitingRestore) { RestoreRenderedMs = now - LastInputMs; awaitingRestore = false; } }
    public bool Settle(double now)
    {
        if (!Moving || now - LastInputMs < RestoreDelayMs) return false;
        Moving = false; RestoreMs = now - LastInputMs; return true;
    }
    public int Limit => Quality switch
    {
        PreviewQuality.Low => Moving ? 75_000 : 100_000,
        PreviewQuality.Medium => Moving ? 100_000 : 250_000,
        PreviewQuality.High => Moving ? 100_000 : 500_000,
        _ => Moving ? AdaptiveMovingPoints : 500_000
    };
    public void Frame(double milliseconds)
    {
        if (Moving && milliseconds > 30) AdaptiveMovingPoints = 75_000;
        else if (Moving && milliseconds < 20) AdaptiveMovingPoints = 100_000;
    }
}

public sealed class PreviewFrames
{
    readonly Queue<double> intervals = new();
    long previous;
    public double LastSubmissionMs { get; private set; }
    public double MeanFrameMs => intervals.Count == 0 ? 0 : intervals.Average();
    public double Fps => MeanFrameMs > 0 ? 1000 / MeanFrameMs : 0;
    public double P95FrameMs => intervals.Count == 0 ? 0 : intervals.Order().ElementAt((int)((intervals.Count - 1) * .95));
    public int SampleCount => intervals.Count;
    public void Record(long started, bool moving)
    {
        LastSubmissionMs = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        if (moving && previous != 0)
        {
            var elapsed = Stopwatch.GetElapsedTime(previous, started).TotalMilliseconds;
            intervals.Enqueue(elapsed);
            if (intervals.Count > 120) intervals.Dequeue();
        }
        previous = moving ? started : 0;
    }
    public void Reset() { intervals.Clear(); previous = 0; }
}

public static class PreviewBuffers
{
    // A deterministic progressive ordering makes every prefix cover the whole
    // preview. Upload once; changing quality never filters or uploads on orbit.
    public static float[] Points(float[] source, Func<Vector3, bool> inside)
    {
        var indices = new List<int>(source.Length / 7);
        for (var i = 0; i < source.Length; i += 7)
            if (inside(Camera.Position(source, i))) indices.Add(i);
        var count = Math.Min(indices.Count, SceneData.PreviewPointLimit);
        var data = new float[count * 7];
        if (count == 0) return data;
        var bits = BitOperations.Log2((uint)(count - 1)) + 1;
        var capacity = 1 << bits; var cursor = 0;
        for (uint i = 0; i < capacity && cursor < count; i++)
        {
            var reversed = i;
            reversed = ((reversed & 0x55555555) << 1) | ((reversed >> 1) & 0x55555555);
            reversed = ((reversed & 0x33333333) << 2) | ((reversed >> 2) & 0x33333333);
            reversed = ((reversed & 0x0f0f0f0f) << 4) | ((reversed >> 4) & 0x0f0f0f0f);
            reversed = ((reversed & 0x00ff00ff) << 8) | ((reversed >> 8) & 0x00ff00ff);
            reversed = (reversed << 16) | (reversed >> 16);
            var index = reversed >> (32 - bits);
            if (index >= count) continue;
            var original = (int)((long)index * indices.Count / count);
            Array.Copy(source, indices[original], data, cursor++ * 7, 7);
        }
        return data;
    }

    public sealed record Batch(string Storey, Vector4 Material, int Offset, int Count);
    public sealed record Mesh(float[] Vertices, List<Batch> Batches, int RemovedTriangles);
    public static Mesh Model(IEnumerable<SceneElement> elements)
    {
        var groups = new Dictionary<(string, Vector4), List<float>>();
        var seen = new Dictionary<(string, Vector4), HashSet<(Vector3, Vector3, Vector3)>>();
        var removed = 0;
        static int Compare(Vector3 a, Vector3 b)
        { var c = a.X.CompareTo(b.X); if (c != 0) return c; c = a.Y.CompareTo(b.Y); return c != 0 ? c : a.Z.CompareTo(b.Z); }
        foreach (var e in elements)
            for (var i = 0; i < e.Triangles.Length; i += 21)
            {
                var t = e.Triangles;
                var key = (e.StoreyId, new Vector4(t[i+3], t[i+4], t[i+5], t[i+6]));
                if (!groups.TryGetValue(key, out var group))
                { groups[key] = group = []; seen[key] = []; }
                var a = Camera.Position(t, i); var b = Camera.Position(t, i+7); var c = Camera.Position(t, i+14);
                if (Compare(a,b)>0) (a,b)=(b,a); if (Compare(b,c)>0) (b,c)=(c,b); if (Compare(a,b)>0) (a,b)=(b,a);
                if (Vector3.Cross(b-a,c-a).LengthSquared() < 1e-18f || !seen[key].Add((a,b,c))) { removed++; continue; }
                for (var j = 0; j < 21; j++) group.Add(t[i+j]);
            }
        var vertices = new List<float>(); var batches = new List<Batch>();
        foreach (var (key, group) in groups)
        { batches.Add(new Batch(key.Item1,key.Item2,vertices.Count/7,group.Count/7)); vertices.AddRange(group); }
        return new Mesh(vertices.ToArray(),batches,removed);
    }
}
