using System.Numerics;
using System.Text.Json.Nodes;
using Punctora.Desktop;

if(args.Length!=1)throw new ArgumentException("Pass a generated elements.json to check the native slab preview");
var model=JsonNode.Parse(File.ReadAllText(args[0]))!.AsObject();
var temporary=Path.Combine(Path.GetTempPath(),"punctora-slab-check-"+Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(Path.Combine(temporary,"assets"));
try
{
    File.WriteAllBytes(Path.Combine(temporary,"assets","preview.bin"),new byte[24]);
    var state=new JsonObject{["assets_directory"]="assets",["model"]=model,
        ["preview"]=new JsonObject{["path"]="preview.bin",["point_count"]=1,["source_point_count"]=1L}};
    var scene=SceneData.Load(Path.Combine(temporary,"check.punctora"),state);
    var unchanged=state.ToJsonString();
    var density=new PreviewDensity();
    density.Input(10);
    if(density.Limit!=100_000||density.Settle(159))throw new Exception("Adaptive moving budget or restore timer changed");
    density.Frame(35);
    if(density.Limit!=75_000||!density.Settle(160)||density.Limit!=500_000)throw new Exception("Adaptive budget did not restore");
    foreach(var (quality, moving, resting) in new[]{(PreviewQuality.Low,75_000,100_000),(PreviewQuality.Medium,100_000,250_000),(PreviewQuality.High,100_000,500_000)})
    {
        density.Quality=quality;density.Input(200);
        if(density.Limit!=moving)throw new Exception("Quality moving budget changed");
        density.Settle(350);
        if(density.Limit!=resting)throw new Exception("Quality resting budget changed");
    }
    var source=new float[500_000*7];
    for(var i=0;i<500_000;i++){source[i*7]=i;source[i*7+6]=1;}
    var progressive=PreviewBuffers.Points(source,_=>true);
    if(progressive.Length!=source.Length||Enumerable.Range(0,500_000).Select(i=>progressive[i*7]).Distinct().Count()!=500_000)throw new Exception("Progressive buffer lost or duplicated a preview point");
    var orbitPoints=Enumerable.Range(0,75_000).Select(i=>progressive[i*7]).ToArray();
    if(orbitPoints.Max()-orbitPoints.Min()<499_000)throw new Exception("Moving subset is spatially concentrated");
    var cropped=PreviewBuffers.Points(source,p=>p.X>=400_000);
    if(cropped.Length!=100_000*7||cropped.Where((_,i)=>i%7==0).Any(x=>x<400_000))throw new Exception("Progressive crop changed");
    var duplicateMesh=PreviewBuffers.Model(scene.Elements.Concat(scene.Elements));
    var unique=PreviewBuffers.Model(scene.Elements);
    if(duplicateMesh.Vertices.Length!=unique.Vertices.Length||duplicateMesh.RemovedTriangles==0||duplicateMesh.Batches.Count>=scene.Elements.Count*2)throw new Exception("Material batching retained overlapping surfaces");
    if(state.ToJsonString()!=unchanged)throw new Exception("Render preparation changed the export model");
    var checkedFaces=0;
    foreach(var slabNode in model["slabs"]!.AsArray())
    {
        var slab=slabNode!.AsObject();
        var element=scene.Elements.Single(e=>e.Id==slab["id"]!.GetValue<string>());
        var expected=(slab["preview_geometry"]!["render_surface_triangles_xy"]??slab["preview_geometry"]!["surface_triangles_xy"])!.AsArray();
        var top=(float)(slab["base"]!.GetValue<double>()+slab["thickness"]!.GetValue<double>());
        var area=0d;
        for(var i=0;i<element.Triangles.Length;i+=21)
        {
            var a=Camera.Position(element.Triangles,i);var b=Camera.Position(element.Triangles,i+7);var c=Camera.Position(element.Triangles,i+14);
            if(!float.IsFinite(a.X)||!float.IsFinite(b.Y)||!float.IsFinite(c.Z))throw new Exception("Nonfinite preview triangle");
            if(Math.Abs(a.Z-top)>1e-5||Math.Abs(b.Z-top)>1e-5||Math.Abs(c.Z-top)>1e-5)continue;
            area+=Math.Abs((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X))/2;
            checkedFaces++;
        }
        var expectedArea=0d;
        foreach(var triangle in expected)
        {
            Vector2 Point(int i)=>new((float)triangle![i]![0]!.GetValue<double>(),(float)triangle![i]![1]!.GetValue<double>());
            var a=Point(0);var b=Point(1);var c=Point(2);
            expectedArea+=Math.Abs((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X))/2;
        }
        if(Math.Abs(area-expectedArea)>Math.Max(.001,expectedArea*.001))throw new Exception("Desktop slab cap differs from void-cut mesh");
    }
    foreach(var kind in new[]{"landings","slab_openings"})foreach(var node in model[kind]?.AsArray()??[])
    {
        if(node!["evidence"]?["floor_integrated"]?.GetValue<bool>()==true)continue;
        if(kind=="slab_openings"&&node["preview_geometry"]?["ifc_cut_eligible"]?.GetValue<bool>()!=true)
        {
            var marker=scene.Elements.Single(e=>e.Id==node["id"]!.GetValue<string>());
            var host=model["slabs"]!.AsArray().Single(s=>s!["id"]!.GetValue<string>()==node["host_slab_id"]!.GetValue<string>())!;
            if(marker.Triangles.Length==0||Enumerable.Range(0,marker.Triangles.Length/7).Min(i=>marker.Triangles[i*7+2])<host["base"]!.GetValue<double>()+host["thickness"]!.GetValue<double>())throw new Exception("Review candidate hidden inside filled slab");
            continue;
        }
        var elements=scene.Elements.Where(e=>e.Id==node["id"]!.GetValue<string>()).ToArray();
        if(elements.Length!=1)throw new Exception("Missing polygon preview");
        var mesh=(node["preview_geometry"]!["render_surface_triangles_xy"]??node["preview_geometry"]!["surface_triangles_xy"])!.AsArray();
        if(mesh.Count==0)throw new Exception("Empty polygon cap");
        var vertices=elements[0].Triangles;
        var expectedArea=0d;var actualArea=0d;
        for(var i=0;i<mesh.Count;i++)
        {
            var tri=mesh[i]!;
            double X(int j)=>tri[j]![0]!.GetValue<double>();double Y(int j)=>tri[j]![1]!.GetValue<double>();
            expectedArea+=Math.Abs((X(1)-X(0))*(Y(2)-Y(0))-(Y(1)-Y(0))*(X(2)-X(0)))/2;
            var a=Camera.Position(vertices,i*42);var b=Camera.Position(vertices,i*42+7);var c=Camera.Position(vertices,i*42+14);
            actualArea+=Math.Abs((double)(b.X-a.X)*(c.Y-a.Y)-(double)(b.Y-a.Y)*(c.X-a.X))/2;
        }
        if(Math.Abs(expectedArea-actualArea)>Math.Max(1e-6,expectedArea*.001))throw new Exception("Polygon cap area changed in desktop preview");
    }
    var redundant=new Vector2[]{new(0,0),new(1,0),new(1,0),new(2,0),new(2,2),new(1,2),new(1,1),new(0,1),new(0,0)};
    var capArea=SceneData.Triangulate(redundant).Sum(t=>{var a=redundant[t[0]];var b=redundant[t[1]];var c=redundant[t[2]];return Math.Abs((b.X-a.X)*(c.Y-a.Y)-(b.Y-a.Y)*(c.X-a.X))/2;});
    if(Math.Abs(capArea-3)>1e-6)throw new Exception("Concave fallback triangulation changed polygon area");
    Console.WriteLine($"Native preview verified: {model["slabs"]!.AsArray().Count} slabs, {checkedFaces} void-cut cap triangles, all landing and void contours");
}
finally
{
    // Only this process's unique temporary fixture is removed.
    Directory.Delete(temporary,true);
}
