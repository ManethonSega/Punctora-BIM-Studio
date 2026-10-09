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
    public string? Storey { get; set; }
    public string? Selected { get; set; }
}
public sealed class SceneViewport : Grid
{
    public ViewSettings View { get; }=new();
    readonly GpuViewport gpu;
    readonly SoftwareViewport software;
    public Action<string>? BackendChanged;
    public Action<string?>? ElementSelected;
    Point press,last;
    bool dragging,pan;
    public bool SoftwareMode { get; private set; }
    public string Backend { get; private set; }="Initializing graphics";
    public SceneViewport(bool forceSoftware=false)
    {
        ClipToBounds=true; Background=Brushes.Transparent;
        software=new SoftwareViewport(View){IsHitTestVisible=false};
        gpu=new GpuViewport(View){IsHitTestVisible=false};
        Children.Add(software); Children.Add(gpu);
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
        PointerPressed+=(_,e)=>{press=last=e.GetPosition(this); pan=e.GetCurrentPoint(this).Properties.IsRightButtonPressed; dragging=true; e.Pointer.Capture(this);};
        PointerMoved+=(_,e)=>
        {
            if(!dragging)return; var current=e.GetPosition(this); var delta=current-last; last=current;
            if(pan)
            {
                var scale=View.Camera.Span/(float)Math.Max(1,Bounds.Height);
                var right=new Vector3(-MathF.Sin(View.Camera.Yaw),MathF.Cos(View.Camera.Yaw),0);
                var up=Vector3.Normalize(Vector3.Cross(right,new Vector3(MathF.Cos(View.Camera.Yaw)*MathF.Cos(View.Camera.Pitch),MathF.Sin(View.Camera.Yaw)*MathF.Cos(View.Camera.Pitch),MathF.Sin(View.Camera.Pitch))));
                View.Camera.Target+=(-right*(float)delta.X+up*(float)delta.Y)*scale;
            }
            else {View.Camera.Yaw-=(float)delta.X*.008f; View.Camera.Pitch=Math.Clamp(View.Camera.Pitch+(float)delta.Y*.008f,-1.4f,1.4f);}
            Redraw();
        };
        PointerReleased+=(_,e)=>
        {
            var location=e.GetPosition(this);
            if(dragging&&!pan&&Math.Sqrt(Math.Pow(location.X-press.X,2)+Math.Pow(location.Y-press.Y,2))<4&&View.Model)
                ElementSelected?.Invoke(View.Camera.Pick(View.Scene,location,Bounds.Size,View.Storey,View.ZMin,View.ZMax));
            dragging=false; e.Pointer.Capture(null);
        };
        PointerWheelChanged+=(_,e)=>{View.Camera.Span=Math.Clamp(View.Camera.Span*MathF.Exp((float)-e.Delta.Y*.12f),.05f,1e7f);Redraw();e.Handled=true;};
    }
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
        View.Scene=scene; if(fit)View.Camera.Fit(scene); gpu.MarkDirty(); Redraw();
    }
    public void Redraw(){software.InvalidateVisual(); if(!SoftwareMode)gpu.RequestNextFrameRendering();}
    public void CaptureGpu(string path){if(SoftwareMode)return;gpu.CapturePath=path;gpu.RequestNextFrameRendering();}
    public JsonObject Diagnostics()=>new(){["backend"]=Backend,["viewport_width"]=Bounds.Width,["viewport_height"]=Bounds.Height,
        ["render_callbacks"]=SoftwareMode?software.RenderTimes.Count:gpu.RenderTimes.Count,
        ["cpu_render_submission_mean_ms"]=Mean(SoftwareMode?software.RenderTimes:gpu.RenderTimes),
        ["point_buffer_bytes"]=SoftwareMode?0:View.Scene.Points.Length*4,
        ["mesh_buffer_bytes"]=SoftwareMode?0:View.Scene.Elements.Sum(e=>e.Triangles.Length)*4,
        ["cloud_color_mode"]=View.CloudColor.ToString(),["point_size_px"]=View.PointSize,
        ["timing_scope"]="CPU drawing/submission callbacks; excludes GPU completion and compositor; not FPS"};
    static double Mean(List<double> values)=>values.Count==0?0:values.Average();
}

public sealed class SoftwareViewport(ViewSettings view) : Control
{
    public List<double> RenderTimes{get;}=[];
    sealed record Paint(double Depth,Point[] Points,Color Color,bool Triangle);
    public override void Render(DrawingContext context)
    {
        var started=Stopwatch.GetTimestamp();
        context.FillRectangle(new SolidColorBrush(Color.Parse("#101827")),new Rect(Bounds.Size));
        if(Bounds.Width<1||Bounds.Height<1)return;
        var paints=new List<Paint>();
        var scene=view.Scene;
        if(view.Cloud)
        {
            var count=scene.Points.Length/7;
            var stride=Math.Max(1,(int)Math.Ceiling(count/5000.0));
            for(var i=0;i<count;i+=stride)
            {
                var offset=i*7; var pos=Camera.Position(scene.Points,offset);
                if(pos.Z<view.ZMin||pos.Z>view.ZMax)continue;
                var p=view.Camera.Project(pos,Bounds.Size);
                if(p is not { } projected||projected.Z is <0 or >1||projected.X<0||projected.X>Bounds.Width||projected.Y<0||projected.Y>Bounds.Height)continue;
                var rgb=PointCloudPalette.Color(view.CloudColor,scene.Points[offset+3],scene.Points[offset+4],scene.Points[offset+5],
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
                    var projected=clipped.Select(p=>view.Camera.Project(p,Bounds.Size)).ToArray();
                    if(projected.Length<3||projected.Any(p=>p==null))continue;
                    var color=element.Id==view.Selected?Color.FromArgb(Channel(.7f*view.Opacity),255,218,77):Color.FromArgb(Channel(element.Triangles[i+6]*view.Opacity),Channel(element.Triangles[i+3]),Channel(element.Triangles[i+4]),Channel(element.Triangles[i+5]));
                    paints.Add(new Paint(projected.Average(p=>p!.Value.Z),projected.Select(p=>new Point(p!.Value.X,p.Value.Y)).ToArray(),color,true));
                }
        foreach(var paint in paints.OrderByDescending(p=>p.Depth))
        {
            var brush=new SolidColorBrush(paint.Color);
            if(!paint.Triangle){var radius=Math.Max(.5,view.PointSize/2);context.DrawEllipse(brush,null,paint.Points[0],radius,radius);continue;}
            var geometry=new StreamGeometry();
            using(var drawing=geometry.Open()){drawing.BeginFigure(paint.Points[0],true);foreach(var p in paint.Points.Skip(1))drawing.LineTo(p);drawing.EndFigure(true);}
            context.DrawGeometry(brush,new Pen(brush,.3),geometry);
        }
        RenderTimes.Add(Stopwatch.GetElapsedTime(started).TotalMilliseconds);if(RenderTimes.Count>120)RenderTimes.RemoveAt(0);
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
    public bool GraphicsReady{get;private set;}
    public string Backend{get;private set;}="Initializing graphics";
    public Action<string>? Ready,Failed;
    public string? CapturePath;
    int program,vertexShader,fragmentShader,pointBuffer,modelBuffer,vao,depth,width,height;
    int matrixUniform,opacityUniform,zMinUniform,zMaxUniform,highlightUniform,pointSizeUniform,colorModeUniform,cloudMinUniform,cloudMaxUniform;
    bool dirty=true;
    List<(SceneElement Element,int Offset,int Count)> ranges=[];
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void BlendFunction(int source,int destination);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] delegate void ReadPixelsFunction(int x,int y,int width,int height,int format,int type,IntPtr data);
    BlendFunction? blend; ReadPixelsFunction? readPixels;
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
            pointBuffer=gl.GenBuffer();modelBuffer=gl.GenBuffer();vao=gl.GenVertexArray();depth=gl.GenRenderbuffer();
            matrixUniform=gl.GetUniformLocationString(program,"uMatrix");opacityUniform=gl.GetUniformLocationString(program,"uOpacity");
            zMinUniform=gl.GetUniformLocationString(program,"uZMin");zMaxUniform=gl.GetUniformLocationString(program,"uZMax");highlightUniform=gl.GetUniformLocationString(program,"uHighlight");
            pointSizeUniform=gl.GetUniformLocationString(program,"uPointSize");colorModeUniform=gl.GetUniformLocationString(program,"uColorMode");
            cloudMinUniform=gl.GetUniformLocationString(program,"uCloudMin");cloudMaxUniform=gl.GetUniformLocationString(program,"uCloudMax");
            blend=Marshal.GetDelegateForFunctionPointer<BlendFunction>(gl.GetProcAddress("glBlendFunc"));
            readPixels=Marshal.GetDelegateForFunctionPointer<ReadPixelsFunction>(gl.GetProcAddress("glReadPixels"));
            var renderer=gl.Renderer??"Unknown adapter";
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
                Upload(gl,pointBuffer,view.Scene.Points);
                ranges=[];var data=new List<float>();
                foreach(var element in view.Scene.Elements){ranges.Add((element,data.Count/7,element.Triangles.Length/7));data.AddRange(element.Triangles);}
                Upload(gl,modelBuffer,data.ToArray());dirty=false;
            }
            var matrix=view.Camera.Matrix(Bounds.Size);
            gl.UniformMatrix4fv(matrixUniform,1,false,&matrix);
            gl.Uniform1f(zMinUniform,view.ZMin);gl.Uniform1f(zMaxUniform,view.ZMax);
            gl.Uniform1f(pointSizeUniform,view.PointSize);gl.Uniform1f(cloudMinUniform,view.Scene.PointMinimum.Z);gl.Uniform1f(cloudMaxUniform,view.Scene.PointMaximum.Z);
            gl.Uniform1i(highlightUniform,0);gl.Uniform1f(opacityUniform,1);
            gl.DepthMask(0);
            if(view.Model)
            {
                Bind(gl,modelBuffer);gl.Uniform1f(opacityUniform,view.Opacity);gl.Uniform1i(colorModeUniform,0);
                foreach(var range in ranges.Where(r=>view.Storey==null||r.Element.StoreyId==view.Storey))
                {gl.Uniform1i(highlightUniform,range.Element.Id==view.Selected?1:0);gl.DrawArrays(4,range.Offset,(IntPtr)range.Count);}
            }
            gl.DepthMask(1);
            // Overlay observed points on translucent candidates; depth still resolves points against points.
            if(view.Cloud){gl.Uniform1i(highlightUniform,0);gl.Uniform1f(opacityUniform,1);gl.Uniform1i(colorModeUniform,(int)view.CloudColor);Bind(gl,pointBuffer);gl.DrawArrays(0,0,(IntPtr)(view.Scene.Points.Length/7));}
            if(view.Model&&view.Selected!=null)
            {
                gl.Disable(0x0B71);Bind(gl,modelBuffer);gl.Uniform1i(highlightUniform,1);gl.Uniform1f(opacityUniform,view.Opacity*.7f);gl.Uniform1i(colorModeUniform,0);
                foreach(var range in ranges.Where(r=>r.Element.Id==view.Selected&&(view.Storey==null||r.Element.StoreyId==view.Storey)))
                    gl.DrawArrays(4,range.Offset,(IntPtr)range.Count);
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
        }
        catch(Exception e){GraphicsReady=false;Failed?.Invoke("3D drawing failed: "+e.Message);}
    }
    static void Upload(GlInterface gl,int buffer,float[] data)
    {gl.BindBuffer(0x8892,buffer);fixed(float* p=data)gl.BufferData(0x8892,(IntPtr)(data.Length*4),(IntPtr)p,0x88E4);}
    static void Bind(GlInterface gl,int buffer)
    {gl.BindBuffer(0x8892,buffer);gl.EnableVertexAttribArray(0);gl.EnableVertexAttribArray(1);gl.VertexAttribPointer(0,3,0x1406,0,28,IntPtr.Zero);gl.VertexAttribPointer(1,4,0x1406,0,28,(IntPtr)12);}
    protected override void OnOpenGlDeinit(GlInterface gl)
    {
        if(pointBuffer!=0)gl.DeleteBuffer(pointBuffer);if(modelBuffer!=0)gl.DeleteBuffer(modelBuffer);
        if(vao!=0)gl.DeleteVertexArray(vao);if(depth!=0)gl.DeleteRenderbuffer(depth);
        if(program!=0)gl.DeleteProgram(program);if(vertexShader!=0)gl.DeleteShader(vertexShader);if(fragmentShader!=0)gl.DeleteShader(fragmentShader);
        GraphicsReady=false;
    }
}
