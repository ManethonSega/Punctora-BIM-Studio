using System.Numerics;
using System.Text.Json.Nodes;
using Avalonia;

namespace Punctora.Desktop;

public sealed record SceneElement(string Id, string Kind, string StoreyId, string Review, float[] Triangles);

public sealed class SceneData
{
    public float[] Points { get; init; } = [];
    public List<SceneElement> Elements { get; init; } = [];
    public long TotalPoints { get; init; }
    public Vector3 Minimum { get; init; } = new(-1);
    public Vector3 Maximum { get; init; } = new(1);
    public static SceneData Load(string projectPath, JsonObject state)
    {
        var assets = Path.Combine(Path.GetDirectoryName(projectPath)!, state["assets_directory"]!.GetValue<string>());
        var relative = state["preview"]!["path"]!.GetValue<string>();
        var path = Path.GetFullPath(Path.Combine(assets, relative));
        if (!path.StartsWith(Path.GetFullPath(assets) + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Preview path escapes the project");
        var count = state["preview"]!["point_count"]!.GetValue<int>();
        if (count is < 1 or > 100000) throw new InvalidDataException("Preview exceeds its point budget");
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length != count * 24) throw new InvalidDataException("Preview is truncated");
        var points = new float[count * 7];
        var minimum = new Vector3(float.PositiveInfinity); var maximum = new Vector3(float.NegativeInfinity);
        for (var i = 0; i < count; i++)
        {
            for (var j = 0; j < 6; j++)
            {
                var value = BitConverter.Int32BitsToSingle(System.Buffers.Binary.BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(i * 24 + j * 4, 4)));
                if (!float.IsFinite(value)) throw new InvalidDataException("Nonfinite preview value");
                points[i * 7 + j] = value;
            }
            points[i * 7 + 6] = 1;
            var position = new Vector3(points[i*7], points[i*7+1], points[i*7+2]);
            minimum = Vector3.Min(minimum, position); maximum = Vector3.Max(maximum, position);
        }
        var elements = new List<SceneElement>();
        if (state["model"] is JsonObject model)
        {
            foreach (var node in model["walls"]!.AsArray())
            {
                var wall = node!.AsObject();
                var a = XY(wall["start"]!); var b = XY(wall["end"]!);
                var side = Vector2.Normalize(new Vector2(-(b-a).Y, (b-a).X)) * Number(wall, "thickness")/2;
                Add(elements, wall, "Wall", [a-side,b-side,b+side,a+side], Number(wall,"base"),Number(wall,"height"));
            }
            foreach (var node in model["slabs"]!.AsArray())
            {
                var slab = node!.AsObject();
                Add(elements, slab, "Slab", slab["footprint"]!.AsArray().Select(p=>XY(p!)).ToArray(), Number(slab,"base"),Number(slab,"thickness"));
            }
        }
        foreach(var element in elements)
            for(var i=0;i<element.Triangles.Length;i+=7)
            {var position=Camera.Position(element.Triangles,i);minimum=Vector3.Min(minimum,position);maximum=Vector3.Max(maximum,position);}
        return new SceneData { Points = points, Elements = elements, Minimum = minimum, Maximum = maximum,
            TotalPoints = state["preview"]!["source_point_count"]!.GetValue<long>() };
    }

    public static float Number(JsonObject obj, string key) => (float)obj[key]!.GetValue<double>();
    static Vector2 XY(JsonNode p) => new((float)p[0]!.GetValue<double>(), (float)p[1]!.GetValue<double>());
    static void Add(List<SceneElement> elements, JsonObject obj, string kind, Vector2[] polygon, float z, float height)
    {
        var review = obj["review_state"]?.GetValue<string>() ?? "unreviewed";
        var color = review switch { "reviewed" => new Vector4(.18f,.82f,.54f,.5f), "flagged"=>new Vector4(1,.68f,.15f,.55f),
            "rejected"=>new Vector4(.9f,.25f,.35f,.16f), _=>kind=="Wall"?new Vector4(.43f,.62f,1,.4f):new Vector4(.64f,.68f,.78f,.3f) };
        var vertices = new List<float>();
        void Vertex(Vector2 p,float h) { vertices.AddRange([p.X,p.Y,h,color.X,color.Y,color.Z,color.W]); }
        foreach (var tri in Triangulate(polygon))
        {
            foreach (var index in tri) Vertex(polygon[index],z);
            foreach (var index in tri.Reverse()) Vertex(polygon[index],z+height);
        }
        for(var i=0;i<polygon.Length;i++)
        {
            var a=polygon[i]; var b=polygon[(i+1)%polygon.Length];
            Vertex(a,z); Vertex(b,z); Vertex(b,z+height);
            Vertex(a,z); Vertex(b,z+height); Vertex(a,z+height);
        }
        elements.Add(new SceneElement(obj["id"]!.GetValue<string>(),kind,obj["storey_id"]!.GetValue<string>(),review,vertices.ToArray()));
    }
    public static List<int[]> Triangulate(Vector2[] polygon)
    {
        var signed=0f;
        for(var i=0;i<polygon.Length;i++) signed+=Cross(polygon[i],polygon[(i+1)%polygon.Length]);
        var ids=Enumerable.Range(0,polygon.Length).ToList(); if(signed<0) ids.Reverse();
        var result=new List<int[]>();
        while(ids.Count>3)
        {
            var found=false;
            for(var j=0;j<ids.Count;j++)
            {
                var a=ids[(j+ids.Count-1)%ids.Count]; var b=ids[j]; var c=ids[(j+1)%ids.Count];
                if(Cross(polygon[b]-polygon[a],polygon[c]-polygon[b])<=1e-8) continue;
                bool Inside(Vector2 p)=>Cross(polygon[b]-polygon[a],p-polygon[a])>=-1e-8 && Cross(polygon[c]-polygon[b],p-polygon[b])>=-1e-8 && Cross(polygon[a]-polygon[c],p-polygon[c])>=-1e-8;
                if(ids.Any(k=>k!=a&&k!=b&&k!=c&&Inside(polygon[k]))) continue;
                result.Add([a,b,c]); ids.RemoveAt(j); found=true; break;
            }
            if(!found) throw new InvalidDataException("Preview footprint cannot be triangulated");
        }
        if(ids.Count==3) result.Add(ids.ToArray());
        return result;
    }
    static float Cross(Vector2 a,Vector2 b)=>a.X*b.Y-a.Y*b.X;
}

public sealed class Camera
{
    public Vector3 Target { get; set; }
    public float Span { get; set; }=12;
    public float Yaw { get; set; }=-.8f;
    public float Pitch { get; set; }=.55f;
    public void Fit(SceneData scene)
    {
        Target=(scene.Minimum+scene.Maximum)/2;
        Span=Math.Max(1,Vector3.Distance(scene.Minimum,scene.Maximum));
    }
    public Matrix4x4 Matrix(Size size)
    {
        var eye=Target+new Vector3(MathF.Cos(Yaw)*MathF.Cos(Pitch),MathF.Sin(Yaw)*MathF.Cos(Pitch),MathF.Sin(Pitch))*Span*1.6f;
        return Matrix4x4.CreateLookAt(eye,Target,Vector3.UnitZ)*Matrix4x4.CreatePerspectiveFieldOfView(.75f,(float)Math.Max(.01,size.Width/Math.Max(1,size.Height)),Math.Max(.0001f,Span*.00001f),Span*10+100);
    }
    public static Vector3 Position(float[] data,int start)=>new(data[start],data[start+1],data[start+2]);
    public Vector3? Project(Vector3 point,Size size)
    {
        var p=Vector4.Transform(new Vector4(point,1),Matrix(size));
        if(p.W<=0) return null;
        return new Vector3((p.X/p.W+1)*(float)size.Width/2,(1-p.Y/p.W)*(float)size.Height/2,p.Z/p.W);
    }
    public string? Pick(SceneData scene,Point location,Size size,string? storey,float zMin,float zMax)
    {
        if(!Matrix4x4.Invert(Matrix(size),out var inverse)) return null;
        Vector3 Unproject(float z)
        {
            var p=Vector4.Transform(new Vector4((float)(2*location.X/size.Width-1),(float)(1-2*location.Y/size.Height),z,1),inverse);
            return new Vector3(p.X,p.Y,p.Z)/p.W;
        }
        var origin=Unproject(0); var direction=Vector3.Normalize(Unproject(1)-origin);
        var distance=float.PositiveInfinity; string? selected=null;
        foreach(var element in scene.Elements.Where(e=>storey==null||e.StoreyId==storey))
            for(var i=0;i<element.Triangles.Length;i+=21)
            {
                var a=Position(element.Triangles,i); var b=Position(element.Triangles,i+7); var c=Position(element.Triangles,i+14);
                var edge=b-a; var other=c-a; var h=Vector3.Cross(direction,other); var determinant=Vector3.Dot(edge,h);
                if(Math.Abs(determinant)<1e-8) continue;
                var s=origin-a; var u=Vector3.Dot(s,h)/determinant; if(u<0||u>1) continue;
                var q=Vector3.Cross(s,edge); var v=Vector3.Dot(direction,q)/determinant; if(v<0||u+v>1) continue;
                var t=Vector3.Dot(other,q)/determinant; var z=(origin+direction*t).Z;
                if(t>0&&t<distance&&z>=zMin&&z<=zMax) {distance=t; selected=element.Id;}
            }
        return selected;
    }
}
