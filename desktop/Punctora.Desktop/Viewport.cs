using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.OpenGL;
using Avalonia.OpenGL.Controls;
using Avalonia.Threading;

namespace Punctora.Desktop;

public enum CloudColorMode { Original, Height, Monochrome }

public static class PointCloudPalette
{
    public static Vector3 Color(CloudColorMode mode,float red,float green,float blue,float z,float minimum,float maximum)
    {
        if(mode==CloudColorMode.Original)return new Vector3(red,green,blue);
        if(mode==CloudColorMode.Monochrome)return new Vector3(.82f,.87f,.92f);
        var t=Math.Clamp((z-minimum)/Math.Max(1e-6f,maximum-minimum),0,1);
        return t<.33f?Vector3.Lerp(new Vector3(.08f,.32f,.9f),new Vector3(.08f,.86f,.78f),t/.33f)
            :t<.66f?Vector3.Lerp(new Vector3(.08f,.86f,.78f),new Vector3(1,.83f,.2f),(t-.33f)/.33f)
            :Vector3.Lerp(new Vector3(1,.83f,.2f),new Vector3(.95f,.23f,.28f),(t-.66f)/.34f);
    }
}
public sealed class ViewSettings
{
    public SceneData Scene { get; set; }=new();
    public Camera Camera { get; }=new();
    public bool Cloud { get; set; }=true;
    public bool Model { get; set; }=true;
    public float Opacity { get; set; }=1;
    public float ZMin { get; set; }=-1e20f;
    public float ZMax { get; set; }=1e20f;
    public CloudColorMode CloudColor { get; set; }=CloudColorMode.Height;
    public float PointSize { get; set; }=2.5f;
    public PreviewDensity Density { get; }=new();
    public float[] PreviewPoints { get; set; }=[];
    public List<Vector2>? CropPolygon { get; set; }
    public float? CropBottom { get; set; }
    public float? CropTop { get; set; }
    public string? Storey { get; set; }
    public string? Selected { get; set; }
    public bool InsideCrop(Vector3 point)
    {
        if(CropBottom is { } bottom&&point.Z<bottom||CropTop is { } top&&point.Z>top)return false;
        if(CropPolygon is not { Count:>=3 } polygon)return true;
        var inside=false;var previous=polygon[^1];
        foreach(var current in polygon)
        {
            if(((previous.Y>point.Y)!=(current.Y>point.Y))
                &&point.X<(current.X-previous.X)*(point.Y-previous.Y)/(current.Y-previous.Y)+previous.X)inside=!inside;
            previous=current;
        }
        return inside;
    }
}
public sealed class SceneViewport : Grid
{
    public ViewSettings View { get; }=new();
    readonly GpuViewport gpu;
    readonly SoftwareViewport software;
    readonly CropOverlay cropOverlay;
    public Action<string>? BackendChanged;
    public Action<string?>? ElementSelected;
    public Action<string>? FrameDiagnosticsChanged;
    Point press,last;
    bool dragging,pan;
    bool framePending, cameraPending;
    float pressYaw,pressPitch;
    Vector3 pressTarget;
    readonly DispatcherTimer settleTimer=new(){Interval=TimeSpan.FromMilliseconds(20)};
    public long CoalescedMoves { get; private set; }
    public int PendingFrames=>framePending?1:0;
    public double LastInputLatencyMs { get; private set; }
    readonly List<Vector2> cropDraft=[];
    public bool CropDrawing { get; private set; }
    public int CropDraftCount=>cropDraft.Count;
    public bool SoftwareMode { get; private set; }
    public string Backend { get; private set; }="Initializing graphics";
    public SceneViewport(bool forceSoftware=false)
    {
        ClipToBounds=true; Background=Brushes.Transparent;
        software=new SoftwareViewport(View){IsHitTestVisible=false};
        gpu=new GpuViewport(View){IsHitTestVisible=false};
        cropOverlay=new CropOverlay(View,cropDraft,()=>CropDrawing){IsHitTestVisible=false};
        Children.Add(software); Children.Add(gpu); Children.Add(cropOverlay);
        settleTimer.Tick+=(_,_)=>
        {
            if(View.Density.Settle(PreviewDensity.Now)){settleTimer.Stop();Redraw();}
        };
        var diagnosticsTimer=new DispatcherTimer{Interval=TimeSpan.FromMilliseconds(250)};
        diagnosticsTimer.Tick+=(_,_)=>
        {
            var frames=SoftwareMode?software.Frames:gpu.Frames;
            FrameDiagnosticsChanged?.Invoke($"{frames.Fps:F1} FPS during movement · {frames.MeanFrameMs:F1} ms/frame · {ActivePoints:N0} points · {View.Density.Quality}");
        };
        AttachedToVisualTree+=(_,_)=>diagnosticsTimer.Start();
        DetachedFromVisualTree+=(_,_)=>{diagnosticsTimer.Stop();settleTimer.Stop();};
        gpu.Ready=backend=>Dispatcher.UIThread.Post(()=>{if(SoftwareMode)return;software.IsVisible=false;Backend=backend; BackendChanged?.Invoke(backend);});
        gpu.Failed=reason=>Dispatcher.UIThread.Post(()=>UseSoftware(reason));
        if(forceSoftware) UseSoftware("Selected in settings");
        else
        {
            var timer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(4)};
            timer.Tick+=(_,_)=>{timer.Stop(); if(!gpu.GraphicsReady) UseSoftware("Graphics initialization unavailable");};
            AttachedToVisualTree+=(_,_)=>timer.Start();
            DetachedFromVisualTree+=(_,_)=>timer.Stop();
        }
        PointerPressed+=(_,e)=>
        {
            if(CropDrawing)
            {
                var properties=e.GetCurrentPoint(this).Properties;
                if(properties.IsRightButtonPressed&&cropDraft.Count>0)cropDraft.RemoveAt(cropDraft.Count-1);
                else if(properties.IsLeftButtonPressed&&View.Camera.IntersectZ(e.GetPosition(this),Bounds.Size,(View.Scene.PointMinimum.Z+View.Scene.PointMaximum.Z)/2) is { } point)
                    cropDraft.Add(new Vector2(point.X,point.Y));
                cropOverlay.InvalidateVisual();e.Handled=true;return;
            }
            press=last=e.GetPosition(this); pan=e.GetCurrentPoint(this).Properties.IsRightButtonPressed; dragging=true; e.Pointer.Capture(this);
            pressYaw=View.Camera.Yaw;pressPitch=View.Camera.Pitch;pressTarget=View.Camera.Target;
        };
        PointerMoved+=(_,e)=>
        {
            if(!dragging)return;
            QueueCamera(e.GetPosition(this));
        };
        PointerReleased+=(_,e)=>
        {
            if(CropDrawing){e.Handled=true;return;}
            var location=e.GetPosition(this);
            if(dragging){if(last!=location)cameraPending=true;last=location;ApplyCamera();Redraw();}
            if(dragging&&!pan&&Math.Sqrt(Math.Pow(location.X-press.X,2)+Math.Pow(location.Y-press.Y,2))<4&&View.Model)
                ElementSelected?.Invoke(View.Camera.Pick(View.Scene,location,Bounds.Size,View.Storey,View.ZMin,View.ZMax));
            dragging=false; e.Pointer.Capture(null);
        };
        PointerCaptureLost+=(_,_)=>{ApplyCamera();dragging=false;};
        PointerWheelChanged+=(_,e)=>{View.Camera.Span=Math.Clamp(View.Camera.Span*MathF.Exp((float)-e.Delta.Y*.12f),.05f,1e7f);Movement();e.Handled=true;};
    }
    void QueueCamera(Point position)
    {if(cameraPending)CoalescedMoves++;last=position;cameraPending=true;Movement();}
    public void BeginDiagnosticOrbit()
    {press=last=default;pan=false;pressYaw=View.Camera.Yaw;pressPitch=View.Camera.Pitch;pressTarget=View.Camera.Target;}
    public void DiagnosticOrbit(Point position)=>QueueCamera(position);
    void ApplyCamera()
    {
        if(!cameraPending)return;
        var delta=last-press;
        if(pan)
        {
            var scale=View.Camera.Span/(float)Math.Max(1,Bounds.Height);
            var right=new Vector3(-MathF.Sin(pressYaw),MathF.Cos(pressYaw),0);
            var up=Vector3.Normalize(Vector3.Cross(right,new Vector3(MathF.Cos(pressYaw)*MathF.Cos(pressPitch),MathF.Sin(pressYaw)*MathF.Cos(pressPitch),MathF.Sin(pressPitch))));
            View.Camera.Target=pressTarget+(-right*(float)delta.X+up*(float)delta.Y)*scale;
        }
        else {View.Camera.Yaw=pressYaw-(float)delta.X*.008f;View.Camera.Pitch=Math.Clamp(pressPitch+(float)delta.Y*.008f,-1.4f,1.4f);}
        LastInputLatencyMs=PreviewDensity.Now-View.Density.LastInputMs;
        cameraPending=false;
    }
    public void Movement(){View.Density.Input(PreviewDensity.Now);settleTimer.Start();Redraw();}
    public int ActivePoints=>SoftwareMode?software.ActivePointCount:gpu.ActivePointCount;
    public void SetQuality(PreviewQuality quality){View.Density.Quality=quality;Redraw();}
    public void UseSoftware(string reason)
    {
        SoftwareMode=true; gpu.IsVisible=false; software.IsVisible=true;
        Backend="Software preview (5,000 points): "+reason; BackendChanged?.Invoke(Backend); Redraw();
    }
    public void UseAutomatic()
    {
        SoftwareMode=false; gpu.IsVisible=true; software.IsVisible=true;
        if(gpu.GraphicsReady) {Backend=gpu.Backend;BackendChanged?.Invoke(Backend);}
        var timer=new DispatcherTimer{Interval=TimeSpan.FromSeconds(4)};
        timer.Tick+=(_,_)=>{timer.Stop();if(!SoftwareMode&&!gpu.GraphicsReady)UseSoftware("Graphics initialization unavailable");};timer.Start();
        Redraw();
    }
    public void SetScene(SceneData scene,bool fit=false)
    {
        View.Scene=scene;View.PreviewPoints=PreviewBuffers.Points(scene.Points,View.InsideCrop);
        if(fit)View.Camera.Fit(scene); gpu.MarkDirty(); Redraw();
    }
    public void SetCrop(IEnumerable<Vector2>? polygon,float? bottom,float? top)
    {
        View.CropPolygon=polygon?.ToList();View.CropBottom=bottom;View.CropTop=top;
        View.PreviewPoints=PreviewBuffers.Points(View.Scene.Points,View.InsideCrop);
        gpu.MarkDirty();cropOverlay.InvalidateVisual();Redraw();
    }
    public void FitVisible()
    {
        var points=View.Scene.Points;var minimum=new Vector3(float.PositiveInfinity);var maximum=new Vector3(float.NegativeInfinity);var found=false;
        for(var offset=0;offset<points.Length;offset+=7)
        {
            var point=Camera.Position(points,offset);if(!View.InsideCrop(point))continue;
            minimum=Vector3.Min(minimum,point);maximum=Vector3.Max(maximum,point);found=true;
        }
        if(!found)View.Camera.Fit(View.Scene);
        else{View.Camera.Target=(minimum+maximum)/2;View.Camera.Span=Math.Max(1,Vector3.Distance(minimum,maximum));}
        Redraw();
    }
    public void BeginCropDrawing()
    {
        cropDraft.Clear();CropDrawing=true;View.Camera.Pitch=1.35f;View.Camera.Fit(View.Scene);cropOverlay.InvalidateVisual();Redraw();
    }
    public Vector2[] FinishCropDrawing()
    {
        if(cropDraft.Count<3)throw new InvalidOperationException("Add at least three crop vertices before applying the crop.");
        var result=cropDraft.ToArray();cropDraft.Clear();CropDrawing=false;cropOverlay.InvalidateVisual();return result;
    }
    public void CancelCropDrawing(){cropDraft.Clear();CropDrawing=false;cropOverlay.InvalidateVisual();}
    public void Redraw()
    {
        if(framePending)return;framePending=true;
        void Frame(TimeSpan _)
        {
            framePending=false;ApplyCamera();cropOverlay.InvalidateVisual();
            if(SoftwareMode)software.InvalidateVisual();else gpu.RequestNextFrameRendering();
        }
        if(TopLevel.GetTopLevel(this) is { } top)top.RequestAnimationFrame(Frame);
        else Dispatcher.UIThread.Post(()=>Frame(default),DispatcherPriority.Render);
    }
    public void CaptureGpu(string path){if(SoftwareMode)return;gpu.CapturePath=path;gpu.RequestNextFrameRendering();}
    public JsonObject Diagnostics()=>new(){["backend"]=Backend,["viewport_width"]=Bounds.Width,["viewport_height"]=Bounds.Height,
        ["graphics_adapter"]=SoftwareMode?"CPU / software":gpu.Adapter,
        ["preview_quality"]=View.Density.Quality.ToString(),["moving"]=View.Density.Moving,
        ["active_points"]=ActivePoints,["orbit_fps"]=(SoftwareMode?software.Frames:gpu.Frames).Fps,
        ["frame_time_mean_ms"]=(SoftwareMode?software.Frames:gpu.Frames).MeanFrameMs,
        ["frame_time_p95_ms"]=(SoftwareMode?software.Frames:gpu.Frames).P95FrameMs,
        ["orbit_frame_samples"]=(SoftwareMode?software.Frames:gpu.Frames).SampleCount,
        ["coalesced_mouse_moves"]=CoalescedMoves,["pending_camera_frames"]=PendingFrames,
        ["latest_input_to_camera_ms"]=LastInputLatencyMs,["density_restore_delay_ms"]=View.Density.RestoreMs,
        ["full_density_frame_delay_ms"]=View.Density.RestoreRenderedMs,
        ["material_batches"]=gpu.MaterialBatchCount,["model_draw_calls"]=gpu.ModelDrawCalls,
        ["removed_overlapping_triangles"]=gpu.RemovedTriangles,
        ["point_buffer_uploads"]=gpu.PointBufferUploads,
        ["render_callbacks"]=SoftwareMode?software.RenderTimes.Count:gpu.RenderTimes.Count,
        ["cpu_render_submission_mean_ms"]=Mean(SoftwareMode?software.RenderTimes:gpu.RenderTimes),
        ["point_buffer_bytes"]=SoftwareMode?0:gpu.VisiblePointCount*7*4,
        ["mesh_buffer_bytes"]=SoftwareMode?0:View.Scene.Elements.Sum(e=>e.Triangles.Length)*4,
        ["cloud_color_mode"]=View.CloudColor.ToString(),["point_size_px"]=View.PointSize,
        ["timing_scope"]="Frame cadence during movement and CPU submission time; excludes GPU completion and physical display presentation"};
    static double Mean(List<double> values)=>values.Count==0?0:values.Average();
}

public sealed class CropOverlay(ViewSettings view,List<Vector2> draft,Func<bool> drawing) : Control
{
    public override void Render(DrawingContext context)
    {
        var polygon=drawing()?draft:view.CropPolygon;
        if(polygon is not { Count:>0 })return;
        var z=(view.Scene.PointMinimum.Z+view.Scene.PointMaximum.Z)/2;
        var points=polygon.Select(p=>view.Camera.Project(new Vector3(p,z),Bounds.Size)).Where(p=>p!=null)
            .Select(p=>new Point(p!.Value.X,p.Value.Y)).ToArray();
        if(points.Length==0)return;
        var brush=new SolidColorBrush(drawing()?Color.Parse("#FBBF24"):Color.Parse("#22D3EE"));var pen=new Pen(brush,2);
        for(var i=1;i<points.Length;i++)context.DrawLine(pen,points[i-1],points[i]);
        if(!drawing()&&points.Length>=3)context.DrawLine(pen,points[^1],points[0]);
        foreach(var point in points)context.DrawEllipse(brush,new Pen(Brushes.Black,1),point,4,4);
    }
}

public sealed class SoftwareViewport(ViewSettings view) : Control
{
    public List<double> RenderTimes{get;}=[];
    public PreviewFrames Frames{get;}=new();
    public int ActivePointCount{get;private set;}
    sealed record Paint(double Depth,Point[] Points,Color Color,bool Triangle,bool Highlight=false);
    public override void Render(DrawingContext context)
    {
        var started=Stopwatch.GetTimestamp();
        context.FillRectangle(new SolidColorBrush(Color.Parse("#101827")),new Rect(Bounds.Size));
        if(Bounds.Width<1||Bounds.Height<1)return;
        var paints=new List<Paint>();
        var scene=view.Scene;
        var matrix=view.Camera.Matrix(Bounds.Size);
        var preview=view.PreviewPoints;
        ActivePointCount=view.Cloud?Math.Min(preview.Length/7,view.Density.Moving?2500:5000):0;
        if(view.Cloud)
        {
            for(var item=0;item<ActivePointCount;item++)
            {
                var offset=item*7; var pos=Camera.Position(preview,offset);
                if(pos.Z<view.ZMin||pos.Z>view.ZMax)continue;
                var p=Camera.Project(pos,Bounds.Size,matrix);
                if(p is not { } projected||projected.Z is <0 or >1||projected.X<0||projected.X>Bounds.Width||projected.Y<0||projected.Y>Bounds.Height)continue;
                var rgb=PointCloudPalette.Color(view.CloudColor,preview[offset+3],preview[offset+4],preview[offset+5],
                    pos.Z,scene.PointMinimum.Z,scene.PointMaximum.Z);
                var color=Color.FromRgb(Channel(rgb.X),Channel(rgb.Y),Channel(rgb.Z));
                paints.Add(new Paint(projected.Z,[new Point(projected.X,projected.Y)],color,false));
            }
        }
        if(view.Model)
            foreach(var element in scene.Elements.Where(e=>view.Storey==null||e.StoreyId==view.Storey))
                for(var i=0;i<element.Triangles.Length;i+=21)
                {
                    var xyz=new[]{Camera.Position(element.Triangles,i),Camera.Position(element.Triangles,i+7),Camera.Position(element.Triangles,i+14)};
                    if(xyz.All(p=>p.Z<view.ZMin)||xyz.All(p=>p.Z>view.ZMax))continue;
                    // Clip actual triangle edges against both section planes.
                    var clipped=ClipPolygon(ClipPolygon(xyz,view.ZMin,true),view.ZMax,false);
                    var projected=clipped.Select(p=>Camera.Project(p,Bounds.Size,matrix)).ToArray();
                    if(projected.Length<3||projected.Any(p=>p==null))continue;
                    var color=Color.FromArgb(Channel(element.Triangles[i+6]*view.Opacity),Channel(element.Triangles[i+3]),Channel(element.Triangles[i+4]),Channel(element.Triangles[i+5]));
                    paints.Add(new Paint(projected.Average(p=>p!.Value.Z),projected.Select(p=>new Point(p!.Value.X,p.Value.Y)).ToArray(),color,true));
                    if(element.Id==view.Selected)paints.Add(paints[^1] with{Color=Color.FromArgb(Channel(.7f*view.Opacity),255,218,77),Highlight=true});
                }
        foreach(var paint in paints.Where(p=>!p.Highlight).OrderByDescending(p=>p.Depth).Concat(paints.Where(p=>p.Highlight)))
        {
            var brush=new SolidColorBrush(paint.Color);
            if(!paint.Triangle){var radius=Math.Max(.5,view.PointSize/2);context.DrawEllipse(brush,null,paint.Points[0],radius,radius);continue;}
            var geometry=new StreamGeometry();
            using(var drawing=geometry.Open()){drawing.BeginFigure(paint.Points[0],true);foreach(var p in paint.Points.Skip(1))drawing.LineTo(p);drawing.EndFigure(true);}
            context.DrawGeometry(brush,new Pen(brush,.3),geometry);
        }
        RenderTimes.Add(Stopwatch.GetElapsedTime(started).TotalMilliseconds);if(RenderTimes.Count>120)RenderTimes.RemoveAt(0);
        Frames.Record(started,view.Density.Moving);
        view.Density.Rendered(PreviewDensity.Now);
    }
    static byte Channel(float v)=>(byte)Math.Clamp(v*255,0,255);
    static Vector3[] ClipPolygon(Vector3[] polygon,float level,bool lower)
    {
        var result=new List<Vector3>();
        for(var i=0;i<polygon.Length;i++)
        {
            var a=polygon[i];var b=polygon[(i+1)%polygon.Length];
            var insideA=lower?a.Z>=level:a.Z<=level;var insideB=lower?b.Z>=level:b.Z<=level;
            if(insideA)result.Add(a);
            if(insideA!=insideB)result.Add(a+(b-a)*((level-a.Z)/(b.Z-a.Z)));
        }
        return result.ToArray();
    }
}

public sealed unsafe class GpuViewport(ViewSettings view) : OpenGlControlBase
{
    public List<double> RenderTimes{get;}=[];
    public PreviewFrames Frames{get;}=new();
    public string Adapter{get;private set;}="Unknown adapter";
    public int ActivePointCount{get;private set;}
    public int MaterialBatchCount=>batches.Count;
    public int ModelDrawCalls{get;private set;}
    public int RemovedTriangles{get;private set;}
    public int PointBufferUploads{get;private set;}
    public bool GraphicsReady{get;private set;}
    public string Backend{get;private set;}="Initializing graphics";
    public Action<string>? Ready,Failed;
    public string? CapturePath;
    public int VisiblePointCount{get;private set;}
    int program,vertexShader,fragmentShader,pointBuffer,modelBuffer,selectionBuffer,vao,depth,width,height;
    int matrixUniform,opacityUniform,zMinUniform,zMaxUniform,highlightUniform,pointSizeUniform,colorModeUniform,cloudMinUniform,cloudMaxUniform;
    bool dirty=true;
    List<PreviewBuffers.Batch> batches=[];
    string? selectionId;
    string? selectionStorey;
    int selectionCount;
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void BlendFunction(int source,int destination);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void ReadPixelsFunction(int x,int y,int width,int height,int format,int type,IntPtr data);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void ColorMaskFunction(byte red,byte green,byte blue,byte alpha);
    BlendFunction? blend; ReadPixelsFunction? readPixels;
    ColorMaskFunction? colorMask;
    public void MarkDirty()=>dirty=true;
    protected override void OnOpenGlInit(GlInterface gl)
    {
        try
        {
            var es=(gl.Version??"").Contains("OpenGL ES");
            var header=es?"#version 300 es\nprecision highp float;\n":"#version 330 core\n";
            vertexShader=gl.CreateShader(0x8B31);
            var error=gl.CompileShaderAndGetError(vertexShader,header+"in vec3 aPosition; in vec4 aColor; uniform mat4 uMatrix; uniform float uPointSize; out vec4 vColor; out float vZ; void main(){gl_Position=uMatrix*vec4(aPosition,1.0);gl_PointSize=uPointSize;vColor=aColor;vZ=aPosition.z;}");
            if(!string.IsNullOrEmpty(error))throw new InvalidOperationException(error);
            fragmentShader=gl.CreateShader(0x8B30);
            error=gl.CompileShaderAndGetError(fragmentShader,header+"in vec4 vColor; in float vZ; uniform float uOpacity; uniform float uZMin; uniform float uZMax; uniform float uCloudMin; uniform float uCloudMax; uniform int uHighlight; uniform int uColorMode; out vec4 color; vec3 heightColor(float t){if(t<.33)return mix(vec3(.08,.32,.9),vec3(.08,.86,.78),t/.33);if(t<.66)return mix(vec3(.08,.86,.78),vec3(1.0,.83,.2),(t-.33)/.33);return mix(vec3(1.0,.83,.2),vec3(.95,.23,.28),(t-.66)/.34);} void main(){if(vZ<uZMin||vZ>uZMax)discard;vec3 c=vColor.rgb;if(uColorMode==1)c=heightColor(clamp((vZ-uCloudMin)/max(.000001,uCloudMax-uCloudMin),0.0,1.0));else if(uColorMode==2)c=vec3(.82,.87,.92);if(uHighlight==1)c=mix(c,vec3(1.0,.86,.25),.8);color=vec4(c,vColor.a*uOpacity);}");
            if(!string.IsNullOrEmpty(error))throw new InvalidOperationException(error);
            program=gl.CreateProgram();gl.AttachShader(program,vertexShader);gl.AttachShader(program,fragmentShader);
            gl.BindAttribLocationString(program,0,"aPosition");gl.BindAttribLocationString(program,1,"aColor");
            error=gl.LinkProgramAndGetError(program);if(!string.IsNullOrEmpty(error))throw new InvalidOperationException(error);
            pointBuffer=gl.GenBuffer();modelBuffer=gl.GenBuffer();selectionBuffer=gl.GenBuffer();vao=gl.GenVertexArray();depth=gl.GenRenderbuffer();
            matrixUniform=gl.GetUniformLocationString(program,"uMatrix");opacityUniform=gl.GetUniformLocationString(program,"uOpacity");
            zMinUniform=gl.GetUniformLocationString(program,"uZMin");zMaxUniform=gl.GetUniformLocationString(program,"uZMax");highlightUniform=gl.GetUniformLocationString(program,"uHighlight");
            pointSizeUniform=gl.GetUniformLocationString(program,"uPointSize");colorModeUniform=gl.GetUniformLocationString(program,"uColorMode");
            cloudMinUniform=gl.GetUniformLocationString(program,"uCloudMin");cloudMaxUniform=gl.GetUniformLocationString(program,"uCloudMax");
            blend=Marshal.GetDelegateForFunctionPointer<BlendFunction>(gl.GetProcAddress("glBlendFunc"));
            readPixels=Marshal.GetDelegateForFunctionPointer<ReadPixelsFunction>(gl.GetProcAddress("glReadPixels"));
            colorMask=Marshal.GetDelegateForFunctionPointer<ColorMaskFunction>(gl.GetProcAddress("glColorMask"));
            var renderer=gl.Renderer??"Unknown adapter";
            Adapter=renderer+" / "+gl.Vendor;
            var software=new[]{"llvmpipe","softpipe","software","swrast","swiftshader","warp","basic render","gdi generic"}.Any(s=>renderer.Contains(s,StringComparison.OrdinalIgnoreCase));
            Backend=(renderer=="Unknown adapter"?"OpenGL (unknown adapter): ":software?"Software OpenGL: ":"Hardware OpenGL: ")+renderer+" / "+gl.Vendor;
            width=height=0;GraphicsReady=true;dirty=true;Ready?.Invoke(Backend);
        }
        catch(Exception e){Failed?.Invoke("3D renderer unavailable: "+e.Message);}
    }
    protected override void OnOpenGlLost(){GraphicsReady=false;Failed?.Invoke("Graphics context lost");}
    protected override void OnOpenGlRender(GlInterface gl,int fb)
    {
        if(!GraphicsReady)return;
        try
        {
            var started=Stopwatch.GetTimestamp();
            var scale=TopLevel.GetTopLevel(this)?.RenderScaling??1;
            var w=Math.Max(1,(int)(Bounds.Width*scale));var h=Math.Max(1,(int)(Bounds.Height*scale));
            gl.BindFramebuffer(0x8D40,fb);
            if(width!=w||height!=h)
            {
                width=w;height=h;gl.BindRenderbuffer(0x8D41,depth);gl.RenderbufferStorage(0x8D41,0x81A5,w,h);
            }
            gl.FramebufferRenderbuffer(0x8D40,0x8D00,0x8D41,depth);
            gl.Viewport(0,0,w,h);gl.ClearColor(.063f,.094f,.153f,1);gl.ClearDepth(1);gl.DepthMask(1);gl.Clear(0x4000|0x0100);
            gl.Enable(0x0B71);gl.DepthFunc(0x0203);gl.Enable(0x0BE2);blend!(0x0302,0x0303);
            if(!(gl.Version??"").Contains("OpenGL ES"))gl.Enable(0x8642);
            gl.BindVertexArray(vao);gl.UseProgram(program);
            if(dirty)
            {
                VisiblePointCount=view.PreviewPoints.Length/7;
                Upload(gl,pointBuffer,view.PreviewPoints);
                PointBufferUploads++;
                var mesh=PreviewBuffers.Model(view.Scene.Elements);
                batches=mesh.Batches;RemovedTriangles=mesh.RemovedTriangles;
                Upload(gl,modelBuffer,mesh.Vertices);dirty=false;selectionId=null;selectionStorey=null;
            }
            ActivePointCount=view.Cloud?Math.Min(VisiblePointCount,view.Density.Limit):0;
            if(selectionId!=view.Selected||selectionStorey!=view.Storey)
            {
                selectionId=view.Selected;selectionStorey=view.Storey;
                var selection=view.Scene.Elements.Where(e=>e.Id==selectionId&&(view.Storey==null||e.StoreyId==view.Storey)).SelectMany(e=>e.Triangles).ToArray();
                selectionCount=selection.Length/7;Upload(gl,selectionBuffer,selection);
            }
            var matrix=view.Camera.Matrix(Bounds.Size);
            gl.UniformMatrix4fv(matrixUniform,1,false,&matrix);
            gl.Uniform1f(zMinUniform,view.ZMin);gl.Uniform1f(zMaxUniform,view.ZMax);
            gl.Uniform1f(pointSizeUniform,view.PointSize);gl.Uniform1f(cloudMinUniform,view.Scene.PointMinimum.Z);gl.Uniform1f(cloudMaxUniform,view.Scene.PointMaximum.Z);
            gl.Uniform1i(highlightUniform,0);gl.Uniform1f(opacityUniform,1);
            ModelDrawCalls=0;
            if(view.Model)
            {
                Bind(gl,modelBuffer);gl.Uniform1f(opacityUniform,view.Opacity);gl.Uniform1i(colorModeUniform,0);
                // Resolve the nearest model skin once, then blend only that
                // surface. Hidden rear and coincident faces cannot accumulate
                // transparent colour or fill work in the colour pass.
                var visible=batches.Where(b=>view.Storey==null||b.Storey==view.Storey).ToArray();
                gl.Disable(0x0BE2);colorMask!(0,0,0,0);gl.DepthMask(1);
                foreach(var batch in visible){gl.DrawArrays(4,batch.Offset,(IntPtr)batch.Count);ModelDrawCalls++;}
                colorMask!(1,1,1,1);gl.Enable(0x0BE2);gl.DepthMask(0);gl.DepthFunc(0x0202);
                foreach(var batch in visible){gl.DrawArrays(4,batch.Offset,(IntPtr)batch.Count);ModelDrawCalls++;}
                gl.DepthFunc(0x0203);
            }
            gl.DepthMask(1);
            // Overlay observed points on translucent candidates; depth still resolves points against points.
            if(view.Cloud){gl.Clear(0x0100);gl.Disable(0x0BE2);gl.Uniform1i(highlightUniform,0);gl.Uniform1f(opacityUniform,1);gl.Uniform1i(colorModeUniform,(int)view.CloudColor);Bind(gl,pointBuffer);gl.DrawArrays(0,0,(IntPtr)ActivePointCount);}
            if(view.Model&&view.Selected!=null)
            {
                gl.Enable(0x0BE2);gl.Disable(0x0B71);Bind(gl,selectionBuffer);gl.Uniform1i(highlightUniform,1);gl.Uniform1f(opacityUniform,view.Opacity*.7f);gl.Uniform1i(colorModeUniform,0);
                gl.DrawArrays(4,0,(IntPtr)selectionCount);
                gl.Enable(0x0B71);
            }
            if(CapturePath is { } path)
            {
                CapturePath=null;var pixels=new byte[w*h*4];fixed(byte* p=pixels)readPixels!(0,0,w,h,0x1908,0x1401,(IntPtr)p);
                using var bitmap=new SkiaSharp.SKBitmap(w,h,SkiaSharp.SKColorType.Rgba8888,SkiaSharp.SKAlphaType.Unpremul);
                for(var row=0;row<h;row++)Marshal.Copy(pixels,(h-row-1)*w*4,bitmap.GetPixels()+row*bitmap.RowBytes,w*4);
                using var image=SkiaSharp.SKImage.FromBitmap(bitmap);using var png=image.Encode(SkiaSharp.SKEncodedImageFormat.Png,100);
                using var file=File.Create(path);png.SaveTo(file);
            }
            gl.BindVertexArray(0);gl.UseProgram(0);
            RenderTimes.Add(Stopwatch.GetElapsedTime(started).TotalMilliseconds);if(RenderTimes.Count>120)RenderTimes.RemoveAt(0);
            Frames.Record(started,view.Density.Moving);view.Density.Frame(Frames.MeanFrameMs);
            view.Density.Rendered(PreviewDensity.Now);
        }
        catch(Exception e){colorMask?.Invoke(1,1,1,1);GraphicsReady=false;Failed?.Invoke("3D drawing failed: "+e.Message);}
    }
    static void Upload(GlInterface gl,int buffer,float[] data)
    {gl.BindBuffer(0x8892,buffer);fixed(float* p=data)gl.BufferData(0x8892,(IntPtr)(data.Length*4),(IntPtr)p,0x88E4);}
    static void Bind(GlInterface gl,int buffer)
    {gl.BindBuffer(0x8892,buffer);gl.EnableVertexAttribArray(0);gl.EnableVertexAttribArray(1);gl.VertexAttribPointer(0,3,0x1406,0,28,IntPtr.Zero);gl.VertexAttribPointer(1,4,0x1406,0,28,(IntPtr)12);}
    protected override void OnOpenGlDeinit(GlInterface gl)
    {
        if(pointBuffer!=0)gl.DeleteBuffer(pointBuffer);if(modelBuffer!=0)gl.DeleteBuffer(modelBuffer);
        if(selectionBuffer!=0)gl.DeleteBuffer(selectionBuffer);
        if(vao!=0)gl.DeleteVertexArray(vao);if(depth!=0)gl.DeleteRenderbuffer(depth);
        if(program!=0)gl.DeleteProgram(program);if(vertexShader!=0)gl.DeleteShader(vertexShader);if(fragmentShader!=0)gl.DeleteShader(fragmentShader);
        GraphicsReady=false;
    }
}
