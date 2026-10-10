using System.Numerics;
using System.Text.Json.Nodes;
using Avalonia;

namespace Punctora.Desktop;

public sealed record SceneElement(string Id, string Kind, string StoreyId, string Review, float[] Triangles);

public sealed class SceneData
{
    public const int PreviewPointLimit = 500_000;
    public float[] Points { get; init; } = [];
    public List<SceneElement> Elements { get; init; } = [];
    public long TotalPoints { get; init; }
    public Vector3 Minimum { get; init; } = new(-1);
    public Vector3 Maximum { get; init; } = new(1);
    public Vector3 PointMinimum { get; init; } = new(-1);
    public Vector3 PointMaximum { get; init; } = new(1);
    public static SceneData Load(string projectPath, JsonObject state)
    {
        var assets = Path.Combine(Path.GetDirectoryName(projectPath)!, state["assets_directory"]!.GetValue<string>());
        var relative = state["preview"]!["path"]!.GetValue<string>();
        var path = Path.GetFullPath(Path.Combine(assets, relative));
        if (!path.StartsWith(Path.GetFullPath(assets) + Path.DirectorySeparatorChar, StringComparison.Ordinal))
            throw new InvalidDataException("Preview path escapes the project");
        var count = state["preview"]!["point_count"]!.GetValue<int>();
        if (count is < 1 or > PreviewPointLimit) throw new InvalidDataException("Preview exceeds its point budget");
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
        var pointMinimum=minimum;var pointMaximum=maximum;
        var elements = new List<SceneElement>();
        if (state["model"] is JsonObject model)
        {
            foreach (var node in model["walls"]!.AsArray())
            {
                var wall = node!.AsObject();
                var a = XY(wall["start"]!); var b = XY(wall["end"]!);
                var direction=Vector2.Normalize(b-a);var length=Vector2.Distance(a,b);
                var side = new Vector2(-direction.Y,direction.X) * Number(wall, "thickness")/2;
                var openings=(model["openings"]?.AsArray()??[]).Where(o=>o!["host_wall_id"]!.GetValue<string>()==wall["id"]!.GetValue<string>()&&o["review_state"]?.GetValue<string>()!="rejected").Select(o=>o!.AsObject()).ToList();
                var cuts=new[]{0f,length}.Concat(openings.SelectMany(o=>new[]{Number(o,"offset"),Number(o,"offset")+Number(o,"width")})).Distinct().Order().ToArray();
                for(var c=0;c<cuts.Length-1;c++)
                {
                    var low=cuts[c];var high=cuts[c+1];var middle=(low+high)/2;
                    var voids=openings.Where(o=>middle>Number(o,"offset")&&middle<Number(o,"offset")+Number(o,"width")).OrderBy(o=>Number(o,"sill")).ToList();
                    var z=0f;
                    void WallPart(float bottom,float top)
                    {
                        if(top-bottom<=1e-6)return;
                        var p=a+direction*low;var q=a+direction*high;
                        Add(elements,wall,"Wall",[p-side,q-side,q+side,p+side],Number(wall,"base")+bottom,top-bottom);
                    }
                    foreach(var opening in voids){WallPart(z,Number(opening,"sill"));z=Math.Max(z,Number(opening,"sill")+Number(opening,"height"));}
                    WallPart(z,Number(wall,"height"));
                }
            }
            foreach (var node in model["slabs"]!.AsArray())
            {
                var slab = node!.AsObject();
                Add(elements, slab, "Slab", slab["footprint"]!.AsArray().Select(p=>XY(p!)).ToArray(), Number(slab,"base"),Number(slab,"thickness"), mesh:slab["preview_geometry"] as JsonObject);
            }
            foreach(var node in model["slab_openings"]?.AsArray()??[])
            {
                var opening=node!.AsObject();
                var slab=model["slabs"]!.AsArray().First(s=>s!["id"]!.GetValue<string>()==opening["host_slab_id"]!.GetValue<string>())!.AsObject();
                Vector2[] footprint;
                if(opening["footprint"] is JsonArray polygon)footprint=polygon.Select(p=>XY(p!)).ToArray();
                else
                {
                    var start=XY(opening["start"]!);var end=XY(opening["end"]!);var direction=Vector2.Normalize(end-start);
                    var side=new Vector2(-direction.Y,direction.X)*Number(opening,"width")/2;
                    footprint=[start-side,end-side,end+side,start+side];
                }
                JsonObject? outlineMesh=opening["preview_geometry"] as JsonObject;
                if(opening["evidence"]?["method"]?.GetValue<string>()=="enclosed_horizontal_occupancy_gap")
                    outlineMesh=new JsonObject{["surface_triangles_xy"]=new JsonArray(),["boundary_rings_xy"]=new JsonArray(new JsonArray(footprint.Select(p=>(JsonNode)new JsonArray((double)p.X,(double)p.Y)).ToArray()))};
                Add(elements,opening,"SlabOpening",footprint,Number(slab,"base")-.01f,Number(slab,"thickness")+.02f,slab["storey_id"]!.GetValue<string>(),outlineMesh);
            }
            foreach(var node in model["openings"]?.AsArray()??[])
            {
                var opening=node!.AsObject();var wall=model["walls"]!.AsArray().First(w=>w!["id"]!.GetValue<string>()==opening["host_wall_id"]!.GetValue<string>())!.AsObject();
                var direction=Vector2.Normalize(XY(wall["end"]!)-XY(wall["start"]!));
                var a=XY(wall["start"]!)+direction*Number(opening,"offset");var b=a+direction*Number(opening,"width");
                var side=new Vector2(-direction.Y,direction.X)*Number(wall,"thickness")/8;
                Add(elements,opening,opening["kind"]!.GetValue<string>(),[a-side,b-side,b+side,a+side],Number(wall,"base")+Number(opening,"sill"),Number(opening,"height"),wall["storey_id"]!.GetValue<string>());
            }
            foreach(var node in model["stairs"]?.AsArray()??[])
            {
                var stair=node!.AsObject();var direction=Vector2.Normalize(XY(stair["end"]!)-XY(stair["start"]!));
                var side=new Vector2(-direction.Y,direction.X)*Number(stair,"width")/2;
                for(var i=0;i<stair["steps"]!.GetValue<int>();i++)
                {
                    var a=XY(stair["start"]!)+direction*Number(stair,"going")*i;var b=a+direction*Number(stair,"going");
                    Add(elements,stair,"Stair",[a-side,b-side,b+side,a+side],Number(stair,"base")+(i+1)*Number(stair,"rise")-Number(stair,"tread_thickness"),Number(stair,"tread_thickness"));
                }
            }
            foreach(var node in model["landings"]?.AsArray()??[])
            {
                var landing=node!.AsObject();
                if(landing["evidence"]?["floor_integrated"]?.GetValue<bool>()==true)continue;
                Add(elements,landing,"Landing",landing["footprint"]!.AsArray().Select(p=>XY(p!)).ToArray(),
                    Number(landing,"base"),Number(landing,"thickness"),mesh:landing["preview_geometry"] as JsonObject);
            }
        }
        foreach(var element in elements)
            for(var i=0;i<element.Triangles.Length;i+=7)
            {var position=Camera.Position(element.Triangles,i);minimum=Vector3.Min(minimum,position);maximum=Vector3.Max(maximum,position);}
        return new SceneData { Points = points, Elements = elements, Minimum = minimum, Maximum = maximum,
            PointMinimum=pointMinimum,PointMaximum=pointMaximum,
            TotalPoints = state["preview"]!["source_point_count"]!.GetValue<long>() };
    }

    public static float Number(JsonObject obj, string key) => (float)obj[key]!.GetValue<double>();
    static Vector2 XY(JsonNode p) => new((float)p[0]!.GetValue<double>(), (float)p[1]!.GetValue<double>());
    static void Add(List<SceneElement> elements, JsonObject obj, string kind, Vector2[] polygon, float z, float height, string? storeyId=null,JsonObject? mesh=null)
    {
        var review = obj["review_state"]?.GetValue<string>() ?? "unreviewed";
        var color = review switch { "reviewed" => new Vector4(.18f,.82f,.54f,.5f), "flagged"=>new Vector4(1,.68f,.15f,.55f),
            "rejected"=>new Vector4(.9f,.25f,.35f,.16f), _=>kind switch {"Wall"=>new Vector4(.43f,.62f,1,.4f),"Stair"=>new Vector4(.9f,.45f,.72f,.7f),"Landing"=>new Vector4(.98f,.55f,.32f,.65f),"SlabOpening"=>new Vector4(.75f,.25f,.95f,.72f),"door"=>new Vector4(.95f,.65f,.25f,.5f),"window"=>new Vector4(.2f,.85f,.9f,.35f),"unknown"=>new Vector4(.95f,.85f,.25f,.45f),_=>new Vector4(.64f,.68f,.78f,.3f)} };
        var vertices = new List<float>();
        void Vertex(Vector2 p,float h) { vertices.AddRange([p.X,p.Y,h,color.X,color.Y,color.Z,color.W]); }
        if(mesh?["surface_triangles_xy"] is JsonArray surfaceTriangles)
        {
            foreach(var tri in surfaceTriangles)
            {
                var points=tri!.AsArray().Select(p=>XY(p!)).ToArray();
                foreach(var point in points)Vertex(point,z);
                foreach(var point in points.Reverse())Vertex(point,z+height);
            }
        }
        else foreach (var tri in Triangulate(polygon))
        {
            foreach (var index in tri) Vertex(polygon[index],z);
            foreach (var index in tri.Reverse()) Vertex(polygon[index],z+height);
        }
        Vector2[][] rings=mesh?["boundary_rings_xy"] is JsonArray boundaries
            ?boundaries.Select(r=>r!.AsArray().Select(p=>XY(p!)).ToArray()).ToArray():[polygon];
        foreach(var ring in rings)for(var i=0;i<ring.Length;i++)
        {
            var a=ring[i]; var b=ring[(i+1)%ring.Length];
            Vertex(a,z); Vertex(b,z); Vertex(b,z+height);
            Vertex(a,z); Vertex(b,z+height); Vertex(a,z+height);
        }
        elements.Add(new SceneElement(obj["id"]!.GetValue<string>(),kind,storeyId??obj["storey_id"]!.GetValue<string>(),review,vertices.ToArray()));
    }
    public static List<int[]> Triangulate(Vector2[] polygon)
    {
        // Raster contours and clipped stair envelopes contain collinear points
        // and edges smaller than float precision. Remove only redundant points,
        // preserving the supported concave outline and original vertex indices.
        double Turn(Vector2 a,Vector2 b,Vector2 c)=>(double)(b.X-a.X)*(c.Y-a.Y)-(double)(b.Y-a.Y)*(c.X-a.X);
        var ids=Enumerable.Range(0,polygon.Length).ToList();
        var changed=true;
        while(changed&&ids.Count>3)
        {
            changed=false;
            for(var j=0;j<ids.Count;j++)
            {
                var a=polygon[ids[(j+ids.Count-1)%ids.Count]];var b=polygon[ids[j]];var c=polygon[ids[(j+1)%ids.Count]];
                var length=Vector2.Distance(a,c);
                if(a==b||b==c||(Math.Abs(Turn(a,b,c))<=1e-7*Math.Max(1,length)&&Vector2.Dot(b-a,b-c)<=0))
                {ids.RemoveAt(j);changed=true;break;}
            }
        }
        var signed=0d;
        for(var i=0;i<ids.Count;i++)signed+=Turn(polygon[ids[0]],polygon[ids[i]],polygon[ids[(i+1)%ids.Count]]);
        if(Math.Abs(signed)<1e-12)throw new InvalidDataException("Preview footprint has zero area");
        if(signed<0) ids.Reverse();
        var result=new List<int[]>();
        while(ids.Count>3)
        {
            var found=false;
            for(var j=0;j<ids.Count;j++)
            {
                var a=ids[(j+ids.Count-1)%ids.Count]; var b=ids[j]; var c=ids[(j+1)%ids.Count];
                if(Turn(polygon[a],polygon[b],polygon[c])<=1e-12) continue;
                bool Inside(Vector2 p)=>Turn(polygon[a],polygon[b],p)>=0 && Turn(polygon[b],polygon[c],p)>=0 && Turn(polygon[c],polygon[a],p)>=0;
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
    public Vector3? IntersectZ(Point location,Size size,float z)
    {
        if(size.Width<=0||size.Height<=0||!Matrix4x4.Invert(Matrix(size),out var inverse))return null;
        Vector3 Unproject(float depth)
        {
            var p=Vector4.Transform(new Vector4((float)(2*location.X/size.Width-1),(float)(1-2*location.Y/size.Height),depth,1),inverse);
            return new Vector3(p.X,p.Y,p.Z)/p.W;
        }
        var origin=Unproject(0);var direction=Unproject(1)-origin;
        if(Math.Abs(direction.Z)<1e-8)return null;
        var distance=(z-origin.Z)/direction.Z;
        return distance>0?origin+direction*distance:null;
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
